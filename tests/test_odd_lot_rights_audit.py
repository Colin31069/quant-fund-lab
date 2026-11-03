"""Independent rights equations catch structurally legal forged financial state."""
import json
from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_odd_lot_rights_settlement import conversion, receipt_book
from test_odd_lot_rights_transitions import EX, HASHES, PAY, event, granted, requests, terms

from quant_fund_lab.odd_lot_rights.audit import audit_rights
from quant_fund_lab.odd_lot_rights.codec import canonical, decode_book, encode_book, fingerprint
from quant_fund_lab.odd_lot_rights.settlement import (
    FractionalCashTerms,
    convert_receipt,
    settle_fraction,
)
from quant_fund_lab.odd_lot_rights.transitions import (
    expire_unpaid,
    grant_entitlements,
    revise_entitlements,
    subscribe_batch,
)
from quant_fund_lab.odd_lot_rights.types import EntitlementLeg, RightsBook


def test_audit_multileg_payments_delivery_and_conversion_with_inventory_posting_log(monkeypatch):
    book = receipt_book()
    result = convert_receipt(book,"convert",replace(conversion(book),fee=D("1.5")),3,
                             as_of="2024-01-10T09:00:00+08:00")
    movements = (
        ("delivery","credit","a"*64+":ordinary","ordinary-receipt",5,"2024-01-08"),
        ("convert","debit","a"*64+":ordinary","ordinary-receipt",3,None),
        ("convert","credit","a"*64+":ordinary","ordinary-final",3,"2024-01-11"))
    # A transition replay would hide a matching implementation defect. Forbid it.
    from quant_fund_lab.odd_lot_rights import settlement, transitions

    def forbidden(*args,**kwargs):
        raise AssertionError("audit must not call production transition functions")

    for name in ("grant_entitlements","subscribe_batch","deliver_claim","expire_unpaid","revise_entitlements"):
        monkeypatch.setattr(transitions,name,forbidden)
    monkeypatch.setattr(settlement,"convert_receipt",forbidden)
    monkeypatch.setattr(settlement,"settle_fraction",forbidden)
    before = encode_book(result.book)
    audit = audit_rights(result.book,initial_cash=D(100),recorded_movements=movements)
    assert audit.passed and audit.commands_checked == 4
    assert audit.expected_movements == movements and encode_book(result.book) == before
    wrong = movements[:-1]
    assert not audit_rights(result.book,initial_cash=D(100),recorded_movements=wrong).passed


@pytest.mark.parametrize("field", ["cash","cash_paid","fees_paid","pending","expired","last_payment_session"])
def test_structurally_valid_checkpoint_changes_fail_financial_reconstruction(field):
    original = granted()
    paid = subscribe_batch(original,"pay",requests(original),as_of=PAY).book
    raw = json.loads(encode_book(paid))
    row = raw["book"]["positions"][1]
    if field == "cash":
        raw["book"]["cash"] = "11"
    elif field in {"cash_paid","fees_paid"}:
        row[field] = "51" if field == "cash_paid" else "1"
    elif field == "pending":
        row.update(pending=4,unpaid="1")
    elif field == "expired":
        row.update(pending=4,expired="1")
    else:
        row[field] = "2024-01-02"
    forged = decode_book(canonical(raw))  # Structural constraints still pass.
    before = encode_book(forged)
    audit = audit_rights(forged,initial_cash=D(100))
    assert not audit.passed and any(field in issue for issue in audit.issues)
    assert encode_book(forged) == before


def test_initial_cash_anchor_is_required_and_cannot_be_inferred_from_forged_checkpoint():
    book = granted()
    assert audit_rights(book,initial_cash=D(100)).passed
    wrong = audit_rights(book,initial_cash=D(101))
    assert not wrong.passed and "initial anchor" in wrong.issues[0]
    assert not audit_rights(book,initial_cash=100.).passed


def test_fractional_settlement_reconstructed_independently_and_counterfeit_cash_rejected():
    bonus = replace(event(),legs=(EntitlementLeg("bonus","bonus-class","bonus",D("0.1")),))
    book = grant_entitlements(RightsBook(D(100)),"grant",bonus,15,as_of=EX).book
    payout = FractionalCashTerms(book.positions[0].key,D("0.5"),D(8),"2024-01-09",
                                "2024-01-09T08:00:00+08:00",HASHES)
    result = settle_fraction(book,"fraction",payout,as_of="2024-01-09T09:00:00+08:00")
    assert audit_rights(result.book,initial_cash=D(100)).passed
    wrong = replace(result.book,cash=D(109))
    assert not audit_rights(wrong,initial_cash=D(100)).passed


def test_revision_then_partial_payment_and_unpaid_expiry_reconstruct_all_quantities():
    book = granted()
    revised_event = replace(event(),available_at="2024-01-03T08:00:00+08:00",evidence_sha256=("c"*64,),
        legs=tuple(replace(leg,units_per_parent=D("0.049")) if leg.leg_id == "ordinary" else leg
                   for leg in event().legs))
    book = revise_entitlements(book,"revision",revised_event,as_of=PAY).book
    payment = terms(book,"ordinary","10")
    from quant_fund_lab.odd_lot_rights.types import PaymentRequest

    book = subscribe_batch(book,"pay",(PaymentRequest(payment,2,D("0.1")),),as_of=PAY).book
    book = expire_unpaid(book,"expiry",payment,as_of="2024-01-06T09:00:00+08:00").book
    assert audit_rights(book,initial_cash=D(100)).passed
    row = next(row for row in book.positions if row.leg_id == "ordinary")
    assert row.pending == 2 and row.expired == D("2.9") and book.cash == D("79.9")


def test_rehashed_subscribe_command_cannot_hide_an_invalid_payment_window():
    initial = granted()
    paid = subscribe_batch(initial,"pay",requests(initial),as_of=PAY).book
    raw = json.loads(encode_book(paid))
    receipt = raw["book"]["receipts"][1]
    command = json.loads(receipt["command_json"])
    command["requests"][0]["terms"]["payment_start"] = "2024-01-04"
    receipt.update(command_json=canonical(command),payload_sha256=fingerprint(command))
    forged = decode_book(canonical(raw))
    audit = audit_rights(forged,initial_cash=D(100))
    assert not audit.passed and "window" in audit.issues[0]


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "wrong_security", "wrong_tradability", "bool_units"])
def test_outer_postings_must_match_every_reconstructed_movement_exactly(mutation):
    book = receipt_book()
    expected = audit_rights(book,initial_cash=D(100)).expected_movements
    assert len(expected) == 1
    row = list(expected[0])
    if mutation == "missing":
        provided = ()
    elif mutation == "duplicate":
        provided = (*expected,*expected)
    else:
        if mutation == "wrong_security":
            row[3] = "other-security"
        elif mutation == "wrong_tradability":
            row[5] = "2024-01-07"
        else:
            row[4] = True
        provided = (tuple(row),)
    assert not audit_rights(book,initial_cash=D(100),recorded_movements=provided).passed


def test_audit_is_independent_of_caller_decimal_precision():
    from decimal import localcontext

    book = subscribe_batch(granted(),"pay",requests(granted(),fee="0.125"),as_of=PAY).book
    with localcontext() as context:
        context.prec = 2
        audit = audit_rights(book,initial_cash=D(100))
    assert audit.passed and audit.commands_checked == 2
