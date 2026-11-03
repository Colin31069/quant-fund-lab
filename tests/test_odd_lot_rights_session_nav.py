"""Actual session NAV counts cash, rights, stocks and receivables once each."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D

import pandas as pd
import pytest
from test_odd_lot_rights_session_flow import _post, _start, _step
from test_odd_lot_rights_transitions import HASHES, event
from test_odd_lot_session_events import _fixture as event_fixture

from quant_fund_lab.odd_lot_paper.session import run_odd_lot_session
from quant_fund_lab.odd_lot_rights.inventory import (
    RightsInventory,
    SecurityLot,
    post_rights_transition,
)
from quant_fund_lab.odd_lot_rights.inventory_codec import decode_inventory, encode_inventory
from quant_fund_lab.odd_lot_rights.inventory_valuation import SecurityMark
from quant_fund_lab.odd_lot_rights.session_nav import value_session_nav
from quant_fund_lab.odd_lot_rights.settlement import ReceiptConversionTerms, convert_receipt
from quant_fund_lab.odd_lot_rights.transitions import (
    deliver_claim,
    grant_entitlements,
    subscribe_batch,
)
from quant_fund_lab.odd_lot_rights.types import (
    DeliveryTerms,
    EntitlementLeg,
    PaymentRequest,
    PaymentTerms,
    RightsBook,
)
from quant_fund_lab.odd_lot_rights.valuation import RightsMark


def marks(account, inputs, *, extra_price=D(100)):
    day = str(inputs.data.close.index[inputs.signal_index+1].date())
    known = day+"T08:00:00+08:00"
    prices = inputs.data.raw_close.iloc[inputs.signal_index+1]
    securities = tuple(SecurityMark(symbol, D(str(prices[symbol])) if symbol in prices else extra_price,
                                   day, known, HASHES)
                       for symbol in sorted({row.security_id for row in account.lots}))
    rights = tuple(RightsMark(row.key, component, price, day, known, HASHES)
        for row in account.book.positions
        for component, units, price in (("unpaid", row.unpaid, D(90)), ("pending", row.pending, D(100)))
        if units > 0)
    return securities, rights, day+"T16:05:00+08:00"


def nav(account, inputs, result):
    securities, rights, stamp = marks(account, inputs)
    return value_session_nav(account, inputs, result, securities, rights, as_of=stamp)


def journey(monkeypatch, restart=False):
    data, research, config, runtime, account = _start(monkeypatch)
    frames = []
    for index in range(29, 33):
        inputs, result = _step(data, research, config, runtime, index)
        account = _post(account, inputs, result)
        day = str(data.close.index[index+1].date())
        if index == 29:
            contract = replace(event(), parent_security_id="2330.TW", ex_session=day,
                available_at=day+"T08:00:00+08:00",
                legs=(EntitlementLeg("paid", "ordinary", "subscription", D(1)),))
            account = post_rights_transition(account, grant_entitlements(account.book, "grant", contract, 3,
                                            as_of=day+"T16:01:00+08:00"))
        if restart:
            account = decode_inventory(encode_inventory(account))
        frames.append(nav(account, inputs, result))
        runtime = result.runtime
    terms = PaymentTerms(account.book.positions[0].key, D(10), day, day,
                         day+"T08:00:00+08:00", HASHES)
    account = post_rights_transition(account, subscribe_batch(account.book, "pay",
        (PaymentRequest(terms, 1, D(0)),), as_of=day+"T16:01:00+08:00"))
    frames.append(nav(account, inputs, result))
    return account, inputs, result, frames, day


@pytest.mark.parametrize("restart", [False, True])
def test_real_buy_sell_tplus2_payment_delivery_and_conversion_count_assets_once(monkeypatch, restart):
    account, inputs, result, frames, day = journey(monkeypatch, restart)
    assert [row.nav for row in frames] == [D(570)]*5
    assert [row.sale_receivables for row in frames] == [D(0), D(300), D(300), D(0), D(0)]
    assert [row.cash for row in frames] == [D(0), D(0), D(0), D(300), D(290)]
    assert frames[-1].unpaid_rights == 180 and frames[-1].pending_claims == 100
    assert frames[-1].engine_equity == 300  # Preserved pre-rights engine baseline.
    right = account.book.positions[0]
    delivery = DeliveryTerms(right.key, right.leg.asset_key, "receipt-2330", day, "2025-01-01",
                              day+"T08:00:00+08:00", HASHES, D(0))
    account = post_rights_transition(account, deliver_claim(account.book, "deliver", delivery, 1,
                                    as_of=day+"T16:02:00+08:00"))
    if restart:
        account = decode_inventory(encode_inventory(account))
    delivered = nav(account, inputs, result)
    assert delivered.nav == 570 and delivered.pending_claims == 0 and delivered.held_securities == 100
    assert account.tradable_units("receipt-2330", day) == 0  # Locked still has value.
    conversion = ReceiptConversionTerms(right.key, right.leg.asset_key, "receipt-2330", "final-2330",
        day, "2025-01-01", day+"T08:00:00+08:00", HASHES, D(1))
    account = post_rights_transition(account, convert_receipt(account.book, "convert", conversion, 1,
                                    as_of=day+"T16:03:00+08:00"))
    converted = nav(account, inputs, result)
    assert converted.nav == 569 and converted.cash == 289 and converted.held_securities == 100
    assert result.nav["equity"] == 300 and result.runtime.portfolio.cash == 300


def test_negative_sale_fee_and_buy_reservation_are_disclosures_not_second_nav_deductions(monkeypatch):
    data, research, config, runtime, account = _start(monkeypatch, shortfall=True)
    values = []
    for index in range(29, 31):
        inputs, result = _step(data, research, config, runtime, index)
        account = _post(account, inputs, result)
        values.append(nav(account, inputs, result))
        runtime = result.runtime
    assert [row.nav for row in values] == [D(980), D(960)]
    assert values[-1].cash == 960 and values[-1].buy_payables == 30
    assert values[-1].sale_fee_payables == 10 and values[-1].settled_cash == 1000
    assert values[-1].sale_receivables == 0


def test_real_split_fraction_and_tplus2_receivables_are_not_duplicate_cash():
    inputs = event_fixture()
    lots = (SecurityLot("opening", "2330.TW", 3, "2024-01-01"),)
    account = RightsInventory(D(100), lots, RightsBook(D(100)), lots)
    runtime, values = inputs.runtime, []
    for index in range(4):
        step = replace(inputs, runtime=runtime, signal_index=index)
        result = run_odd_lot_session(step)
        account = _post(account, step, result)
        values.append(nav(account, step, result))
        runtime = result.runtime
    assert [row.nav for row in values] == [D(420), D(420), D(422), D(422)]
    assert [row.fractional_receivables for row in values] == [D(98), D(98), D(0), D(0)]
    assert [row.cash for row in values] == [D(106), D(126), D(226), D(226)]


@pytest.mark.parametrize("change", ["engine_equity", "anchor", "missing", "future", "stale", "duplicate", "wrong_price", "as_of"])
def test_joined_nav_rejects_wrong_baseline_or_unavailable_marks_without_mutation(monkeypatch, change):
    account, inputs, result, _, day = journey(monkeypatch)
    before = encode_inventory(account)
    securities, rights, stamp = marks(account, inputs)
    candidate = deepcopy(result)
    if change == "engine_equity":
        candidate.nav["equity"] += 1
    elif change == "anchor":
        account = RightsInventory(D(0), (), RightsBook(D(0)), ())
    elif change == "missing":
        rights = rights[:-1]
    elif change == "future":
        rights = (replace(rights[0], available_at="2026-01-01T08:00:00+08:00"), *rights[1:])
    elif change == "stale":
        rights = (replace(rights[0], session="2024-01-01"), *rights[1:])
    elif change == "duplicate":
        rights = (*rights, rights[0])
    elif change == "as_of":
        stamp = day+"T16:00:00+08:00"  # Before the payment command.
    else:
        # Give one already delivered current market identity a substituted quote.
        right = account.book.positions[0]
        terms = DeliveryTerms(right.key, right.leg.asset_key, "2330.TW", day, day,
                              day+"T08:00:00+08:00", HASHES, D(0))
        account = post_rights_transition(account, deliver_claim(account.book, "deliver", terms, 1,
                                        as_of=day+"T16:02:00+08:00"))
        securities, rights, stamp = marks(account, inputs)
        securities = (replace(securities[0], unit_value=D(101)),)
        before = encode_inventory(account)
    with pytest.raises(ValueError):
        value_session_nav(account, inputs, candidate, securities, rights, as_of=stamp)
    if change != "anchor":
        assert encode_inventory(account) == before


@pytest.mark.parametrize("change", ["base_currency", "quote_currency"])
def test_session_nav_does_not_treat_foreign_amounts_as_twd(monkeypatch, change):
    data, research, config, runtime, account = _start(monkeypatch)
    inputs, result = _step(data, research, config, runtime, 29)
    account = _post(account, inputs, result)
    if change == "base_currency":
        inputs = replace(inputs, config=replace(config, base_currency="USD"))
    else:
        codes = pd.DataFrame("USD", index=data.close.index, columns=data.close.columns)
        inputs = replace(inputs, data=replace(data, currency_codes=codes))
    with pytest.raises(ValueError, match="TWD"):
        nav(account, inputs, result)


def test_fractional_receivable_nav_drift_cannot_hide_in_matching_engine_equity():
    inputs = event_fixture()
    lots = (SecurityLot("opening", "2330.TW", 3, "2024-01-01"),)
    account = RightsInventory(D(100), lots, RightsBook(D(100)), lots)
    result = run_odd_lot_session(inputs)
    account = _post(account, inputs, result)
    tampered = deepcopy(result)
    tampered.runtime.portfolio.receivable_value += 1
    tampered.nav["receivable_value"] += 1
    tampered.nav["equity"] += 1
    before = encode_inventory(account)
    with pytest.raises(ValueError, match="fractional receivable mark"):
        nav(account, inputs, tampered)
    assert encode_inventory(account) == before
