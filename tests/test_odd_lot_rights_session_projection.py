"""Rights payments/deliveries feed real following sessions without stale cash."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_odd_lot_rights_session_flow import _post, _start, _step
from test_odd_lot_rights_transitions import HASHES, event

from quant_fund_lab.odd_lot_paper.bridge import capture_session_state, restore_session_state
from quant_fund_lab.odd_lot_paper.types import StopState
from quant_fund_lab.odd_lot_rights.inventory import post_rights_transition
from quant_fund_lab.odd_lot_rights.inventory_codec import decode_inventory, encode_inventory
from quant_fund_lab.odd_lot_rights.session_projection import project_rights_session
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
)


def funded(monkeypatch, fee=D(0)):
    data, research, config, runtime, account = _start(monkeypatch)
    inputs, result = _step(data, research, config, runtime, 29)
    account = _post(account, inputs, result)
    day = str(data.close.index[30].date())
    contract = replace(event(), parent_security_id="2330.TW", ex_session=day,
        available_at=day+"T08:00:00+08:00",
        legs=(EntitlementLeg("paid", "ordinary", "subscription", D(1)),))
    account = post_rights_transition(account, grant_entitlements(account.book, "grant", contract, 3,
                                    as_of=day+"T16:01:00+08:00"))
    runtime = result.runtime
    for index in range(30, 33):
        inputs, result = _step(data, research, config, runtime, index)
        account = _post(account, inputs, result)
        runtime = result.runtime
    day = str(data.close.index[33].date())
    terms = PaymentTerms(account.book.positions[0].key, D(10), day, day,
                         day+"T08:00:00+08:00", HASHES)
    account = post_rights_transition(account, subscribe_batch(account.book, "pay",
        (PaymentRequest(terms, 1, fee),), as_of=day+"T16:01:00+08:00"))
    return data, research, config, runtime, account, day


def project(data, runtime, account, day, **kwargs):
    return project_rights_session(account, runtime, completed_session=day,
        origin_session=str(data.close.index[29].date()), session_offset=4,
        completed_index=33, as_of=day+"T16:05:00+08:00", **kwargs)


@pytest.mark.parametrize("restart", [False, True])
def test_real_next_session_spends_post_payment_cash_not_stale_engine_balance(monkeypatch, restart):
    data, research, config, runtime, account, day = funded(monkeypatch)
    original = deepcopy(runtime)
    if restart:
        account = decode_inventory(encode_inventory(account))
    projected = project(data, runtime, account, day)
    assert projected.exact_cash == 290 and runtime.portfolio.cash == 300
    restored = restore_session_state(projected.checkpoint, completed_index=33)
    baseline = capture_session_state(runtime, session=day,
        origin_session=str(data.close.index[29].date()), session_offset=4, completed_index=33)
    assert projected.checkpoint.settlements == baseline.settlements
    assert [{key: value for key, value in row.items() if key != "due_session_index"}
            for row in restored.settlements] == [
        {key: value for key, value in row.items() if key != "due_session_index"}
        for row in runtime.settlements]
    assert [row for row in restored.settlements if row["settled_at"] is None] == [
        row for row in runtime.settlements if row["settled_at"] is None]
    assert restored.receivables == runtime.receivables and restored.pending == runtime.pending
    assert restored.stops == runtime.stops and restored.terminated == runtime.terminated
    assert restored.passive_submitted == runtime.passive_submitted
    inputs, result = _step(data, research, config, restored, 33)
    account = _post(account, inputs, result)
    assert [(row["symbol"], row["quantity"]) for row in result.fills] == [("2317.TW", 2)]
    assert account.cash == 90 and account.book.positions[0].pending == 1
    assert runtime == original


@pytest.mark.parametrize("locked", [False, True])
def test_delivery_projects_owned_shares_separate_from_tradable_units(monkeypatch, locked):
    data, research, config, runtime, account, day = funded(monkeypatch)
    right = account.book.positions[0]
    terms = DeliveryTerms(right.key, right.leg.asset_key, "2330.TW", day,
        "2025-01-01" if locked else day, day+"T08:00:00+08:00", HASHES, D(0))
    account = post_rights_transition(account, deliver_claim(account.book, "deliver", terms, 1,
                                    as_of=day+"T16:02:00+08:00"))
    before = encode_inventory(account)
    with pytest.raises(ValueError, match="explicit stop"):
        project(data, runtime, account, day)
    projected = project(data, runtime, account, day,
                        opening_stops=(StopState("2330.TW", 95., 100., .05),))
    assert projected.checkpoint.shares == (("2330.TW", 1),)
    assert projected.tradable_units == (("2330.TW", 0 if locked else 1),)
    assert projected.exact_cash == 290 and account.book.positions[0].pending == 0
    if not locked:
        restored = restore_session_state(projected.checkpoint, completed_index=33)
        inputs, result = _step(data, research, config, restored, 33)
        account = _post(account, inputs, result)
        assert any(row["symbol"] == "2330.TW" and row["side"] == "SELL"
                   and row["quantity"] == 1 for row in result.fills)
        assert account.cash == 90
    else:
        # Execution must consume the separate capacity in the next adapter.
        assert encode_inventory(account) == before


@pytest.mark.parametrize("change", ["cash", "shares", "session", "future", "extra_stop"])
def test_projection_rejects_stale_anchor_future_knowledge_or_invented_risk(monkeypatch, change):
    data, _, _, runtime, account, day = funded(monkeypatch)
    before = encode_inventory(account)
    kwargs = {}
    if change == "cash":
        runtime.portfolio.cash += 1
    elif change == "shares":
        runtime.portfolio.shares["2330.TW"] = 1
    elif change == "session":
        day = str(data.close.index[32].date())
    elif change == "future":
        with pytest.raises(ValueError, match="future rights knowledge"):
            project_rights_session(account, runtime, completed_session=day,
                origin_session=str(data.close.index[29].date()), session_offset=4,
                completed_index=33, as_of=day+"T16:00:00+08:00")
        return
    else:
        kwargs["opening_stops"] = (StopState("unheld", 95., 100., .05),)
    with pytest.raises(ValueError):
        project(data, runtime, account, day, **kwargs)
    assert encode_inventory(account) == before


def test_projection_refuses_silent_decimal_to_float_loss(monkeypatch):
    data, _, _, runtime, account, day = funded(monkeypatch, D("0.000000000000000001"))
    assert account.cash == D("289.999999999999999999")
    with pytest.raises(ValueError, match="precision loss"):
        project(data, runtime, account, day)


def test_projection_preserves_active_stop_and_unsettled_obligation(monkeypatch):
    data, research, config, runtime, account = _start(monkeypatch)
    inputs, result = _step(data, research, config, runtime, 29)
    account = _post(account, inputs, result)
    day = str(data.close.index[30].date())
    projected = project_rights_session(account, result.runtime, completed_session=day,
        origin_session=str(data.close.index[29].date()), session_offset=1,
        completed_index=30, as_of=day+"T16:05:00+08:00")
    restored = restore_session_state(projected.checkpoint, completed_index=30)
    assert restored.stops == result.runtime.stops and restored.stops
    assert restored.settlements == result.runtime.settlements
    assert restored.settlements[0]["settled_at"] is None
    assert restored.settlements[0]["due_session_index"] == 32
    assert restored.portfolio == result.runtime.portfolio


def test_projection_requires_actual_recorded_session_not_an_opening_balance(monkeypatch):
    data, _, _, runtime, account = _start(monkeypatch)
    day = str(data.close.index[29].date())
    with pytest.raises(ValueError, match="future rights knowledge|engine-session anchor"):
        project(data, runtime, account, day)
