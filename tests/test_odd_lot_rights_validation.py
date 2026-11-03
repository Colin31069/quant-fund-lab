"""Rights checkpoints and valuation reject unknown, stale and malformed evidence."""
import json
from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_odd_lot_rights_transitions import EX, PAY, event, granted, marks, requests

from quant_fund_lab.odd_lot_rights.codec import canonical, decode_book, encode_book, fingerprint
from quant_fund_lab.odd_lot_rights.transitions import grant_entitlements, subscribe_batch
from quant_fund_lab.odd_lot_rights.types import EntitlementLeg, RightsBook
from quant_fund_lab.odd_lot_rights.valuation import value_book


@pytest.mark.parametrize("value", [D("NaN"),D("Infinity"),D(-1),100.,True])
def test_cash_requires_exact_finite_nonnegative_decimal(value):
    with pytest.raises(ValueError):
        RightsBook(value)


def test_future_event_and_naive_clock_cannot_grant_or_value_rights():
    initial = RightsBook(D(100))
    future = replace(event(),available_at="2024-01-03T08:00:00+08:00")
    with pytest.raises(ValueError,match="not available"):
        grant_entitlements(initial,"future",future,100,as_of=EX)
    with pytest.raises(ValueError,match="timezone"):
        grant_entitlements(initial,"naive",event(),100,as_of="2024-01-02T08:00:00")
    assert initial == RightsBook(D(100))


@pytest.mark.parametrize("change", ["missing", "future", "stale", "duplicate", "unrelated"])
def test_missing_or_unusable_rights_prices_never_turn_into_zero_nav(change):
    book = granted()
    values = marks(book,"2024-01-02",after_payment=False)
    if change == "missing":
        values = values[1:]
    elif change == "future":
        values = (replace(values[0],available_at="2024-01-03T08:00:00+08:00"),*values[1:])
    elif change == "stale":
        values = (replace(values[0],session="2024-01-01"),*values[1:])
    elif change == "duplicate":
        values = (*values,values[0])
    else:
        values = (replace(values[0],right_key="unrelated"),*values[1:])
    before = encode_book(book)
    with pytest.raises(ValueError):
        value_book(book,values,as_of=EX)
    assert encode_book(book) == before


def test_explicit_zero_marks_are_distinct_from_missing_and_future_checkpoint_is_rejected():
    book = granted()
    zeros = tuple(replace(row,unit_value=D(0)) for row in marks(book,"2024-01-02",after_payment=False))
    assert value_book(book,zeros,as_of=EX).total_book_value == 100
    paid = subscribe_batch(book,"pay",requests(book),as_of=PAY).book
    with pytest.raises(ValueError,match="future checkpoint"):
        value_book(paid,zeros,as_of=EX)


def test_bonus_fraction_stays_an_explicit_claim_without_rounding_or_cash_invention():
    bonus = replace(event(),legs=(EntitlementLeg("fractional","bonus-class","bonus",D("0.1")),))
    book = grant_entitlements(RightsBook(D(100)),"grant",bonus,5,as_of=EX).book
    row = book.positions[0]
    assert row.entitled == row.unpaid == D("0.5") and row.pending == row.delivered == 0
    assert row.cash_paid == row.fees_paid == 0 and book.cash == 100
    with pytest.raises(ValueError,match="absent"):
        value_book(book,(),as_of=EX)


@pytest.mark.parametrize("mutation", ["cash_number", "extra", "schema", "ownership", "receipt", "clock"])
def test_checkpoint_decode_rejects_type_shape_ownership_and_command_corruption(mutation):
    raw = json.loads(encode_book(granted()))
    if mutation == "cash_number":
        raw["book"]["cash"] = 100
    elif mutation == "extra":
        raw["book"]["hidden"] = True
    elif mutation == "schema":
        raw["schema_version"] = True
    elif mutation == "ownership":
        raw["book"]["positions"][0]["eligible_parent_units"] = 101
    elif mutation == "receipt":
        raw["book"]["receipts"][0]["command_json"] = '{"as_of":"2024-01-02T08:00:00+08:00","kind":"altered"}'
    else:
        raw["book"]["through"] = None
    with pytest.raises((ValueError,TypeError)):
        decode_book(canonical(raw))


def test_duplicate_json_keys_and_future_or_reversed_command_clocks_are_rejected():
    encoded = encode_book(granted())
    with pytest.raises(ValueError,match="duplicate"):
        decode_book(encoded.replace('"schema_version":1','"schema_version":1,"schema_version":1'))
    book = subscribe_batch(granted(),"pay",requests(granted()),as_of=PAY).book
    with pytest.raises(ValueError,match="completed clock"):
        grant_entitlements(book,"backdated",replace(event(),event_id="c"*64),100,as_of=EX)
    with pytest.raises(ValueError,match="receipt sequence"):
        replace(book,through="2024-01-02T08:00:00+08:00")


@pytest.mark.parametrize("mutation", ["one_leg", "all_legs", "ownership_basis"])
def test_event_checkpoint_cannot_drop_legs_or_change_the_shared_grant_basis(mutation):
    raw = json.loads(encode_book(granted()))
    if mutation == "one_leg":
        raw["book"]["positions"] = raw["book"]["positions"][1:]
    elif mutation == "all_legs":
        raw["book"]["positions"] = []
    else:
        row = raw["book"]["positions"][0]
        row.update(eligible_parent_units=200,entitled="20",pending=20)
    with pytest.raises(ValueError,match="event"):
        decode_book(canonical(raw))


@pytest.mark.parametrize("mutation", ["latest_terms", "future_history"])
def test_consistent_state_or_rehashed_command_still_requires_original_available_terms(mutation):
    raw = json.loads(encode_book(granted()))
    if mutation == "latest_terms":
        for row in raw["book"]["positions"]:
            row["event"]["legs"][0]["units_per_parent"] = "0.2"
        raw["book"]["positions"][0].update(entitled="20",pending=20)
        message = "latest recorded terms"
    else:
        receipt = raw["book"]["receipts"][0]
        command = json.loads(receipt["command_json"])
        command["event"]["available_at"] = "2024-01-03T08:00:00+08:00"
        receipt.update(command_json=canonical(command),payload_sha256=fingerprint(command))
        message = "future terms"
    with pytest.raises(ValueError,match=message):
        decode_book(canonical(raw))


def test_terms_and_declared_ownership_reject_unknown_or_inexact_inputs():
    with pytest.raises(ValueError,match="Decimal"):
        EntitlementLeg("leg","asset","subscription",0.05)
    with pytest.raises(ValueError,match="evidence"):
        replace(event(),evidence_sha256=())
    with pytest.raises(ValueError,match="timezone"):
        replace(event(),available_at="2024-01-01T12:00:00")
    with pytest.raises(ValueError,match="explicit integers"):
        grant_entitlements(RightsBook(D(100)),"bool",event(),True,as_of=EX)
