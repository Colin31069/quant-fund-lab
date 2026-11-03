"""Hypothetical three-leg rights accounting conserves quantities and hand-valued NAV."""
from dataclasses import replace
from decimal import Decimal as D
from decimal import localcontext

import pytest

from quant_fund_lab.odd_lot_rights.codec import decode_book, encode_book
from quant_fund_lab.odd_lot_rights.transitions import (
    deliver_claim,
    expire_unpaid,
    grant_entitlements,
    revise_entitlements,
    subscribe_batch,
)
from quant_fund_lab.odd_lot_rights.types import (
    DeliveryTerms,
    EntitlementEvent,
    EntitlementLeg,
    PaymentRequest,
    PaymentTerms,
    RightsBook,
)
from quant_fund_lab.odd_lot_rights.valuation import RightsMark, value_book

EX = "2024-01-02T08:00:00+08:00"
PAY = "2024-01-03T09:00:00+08:00"
DELIVER = "2024-01-08T09:00:00+08:00"
HASHES = ("b"*64,)


def event():
    # Entirely hypothetical quantities/prices, not actual issuer terms.
    return EntitlementEvent("a"*64, "parent-security", "2024-01-02",
        "2024-01-01T12:00:00+08:00", HASHES, (
            EntitlementLeg("bonus", "common-bonus-class", "bonus", D("0.1")),
            EntitlementLeg("ordinary", "common-subscription-class", "subscription", D("0.05")),
            EntitlementLeg("preferred", "preferred-subscription-class", "subscription", D("0.02"))))


def position(book, leg):
    return next(row for row in book.positions if row.leg_id == leg)


def granted(cash="100", parent_units=100):
    return grant_entitlements(RightsBook(D(cash)), "grant", event(), parent_units, as_of=EX).book


def terms(book, leg, price):
    return PaymentTerms(position(book,leg).key, D(price), "2024-01-03", "2024-01-05",
                        "2024-01-03T08:00:00+08:00", HASHES)


def requests(book, fee="0"):
    return (PaymentRequest(terms(book,"ordinary","10"),5,D(fee)),
            PaymentRequest(terms(book,"preferred","20"),2,D(fee)))


def marks(book, session, *, after_payment):
    result = []
    for row in book.positions:
        for component, units in (("unpaid",row.unpaid),("pending",row.pending)):
            if not units:
                continue
            price = {"bonus":"20", "ordinary":"20" if after_payment else "10",
                     "preferred":"25" if after_payment else "5"}[row.leg_id]
            result.append(RightsMark(row.key,component,D(price),session,
                session+"T08:00:00+08:00",HASHES))
    return tuple(result)


def test_multileg_hand_equations_payment_and_later_delivery_never_double_count_assets():
    initial = granted()
    assert position(initial,"bonus").pending == 10
    assert position(initial,"ordinary").unpaid == 5 and position(initial,"preferred").unpaid == 2
    before = value_book(initial,marks(initial,"2024-01-02",after_payment=False),as_of=EX)
    assert before.total_book_value == 360  # 100 cash + 200 bonus + 50 ordinary rights + 10 preferred rights.
    paid = subscribe_batch(initial,"pay",requests(initial),as_of=PAY)
    assert paid.cash_delta == -90 and paid.book.cash == 10
    assert [(row.cash_paid,row.fees_paid) for row in paid.book.positions] == [(D(0),D(0)),(D(50),D(0)),(D(40),D(0))]
    assert value_book(paid.book,marks(paid.book,"2024-01-03",after_payment=True),as_of=PAY).total_book_value == 360
    book, delivered_value = paid.book, D(0)
    for leg, units, price in (("bonus",10,D(20)),("ordinary",5,D(20)),("preferred",2,D(25))):
        row = position(book,leg)
        delivery = DeliveryTerms(row.key,row.leg.asset_key,leg+"-security", "2024-01-08", "2024-01-09",
                                  "2024-01-05T12:00:00+08:00",HASHES,D(0))
        transition = deliver_claim(book,"deliver-"+leg,delivery,units,as_of=DELIVER)
        assert transition.credits[0].units == units and transition.credits[0].tradable_session == "2024-01-09"
        assert transition.cash_delta == 0
        book = transition.book
        delivered_value += units*price
    assert value_book(book,(),as_of=DELIVER).total_book_value == 10
    assert delivered_value + book.cash == 360
    assert all(row.pending == 0 for row in book.positions)


def test_fee_cost_and_partial_election_are_explicit_not_an_implicit_cash_shortfall_policy():
    book = granted()
    result = subscribe_batch(book,"pay",requests(book,fee="0.125"),as_of=PAY)
    assert result.book.cash == D("9.750") and result.cash_delta == D("-90.250")
    assert sum(row.fees_paid for row in result.book.positions) == D("0.250")
    assert value_book(result.book,marks(result.book,"2024-01-03",after_payment=True),as_of=PAY).total_book_value == D("359.750")
    scarce = granted("89")
    snapshot = encode_book(scarce)
    with pytest.raises(ValueError,match="insufficient usable cash"):
        subscribe_batch(scarce,"pay",requests(scarce),as_of=PAY)
    assert encode_book(scarce) == snapshot and all(row.cash_paid == 0 for row in scarce.positions)
    # Explicitly choose only two ordinary units. No automatic preferred-first or prorated allocation.
    chosen = (PaymentRequest(terms(scarce,"ordinary","10"),2,D(0)),)
    result = subscribe_batch(scarce,"chosen",chosen,as_of=PAY)
    assert result.book.cash == 69 and position(result.book,"ordinary").pending == 2
    assert position(result.book,"preferred").pending == 0


def test_later_terms_are_not_required_at_entitlement_and_cannot_be_consumed_early():
    book = granted()
    future = replace(terms(book,"ordinary","10"),available_at="2024-01-04T08:00:00+08:00")
    with pytest.raises(ValueError,match="not available"):
        subscribe_batch(book,"early",(PaymentRequest(future,1,D(0)),),as_of=PAY)
    assert book.cash == 100 and position(book,"ordinary").pending == 0
    paid = subscribe_batch(book,"pay",requests(book),as_of=PAY).book
    row = position(paid,"ordinary")
    delivery = DeliveryTerms(row.key,row.leg.asset_key,"ordinary-receipt", "2024-01-08", "2024-01-09",
                              "2024-01-05T12:00:00+08:00",HASHES,D(0))
    with pytest.raises(ValueError,match="not available"):
        deliver_claim(paid,"early-delivery",delivery,5,as_of=PAY)
    assert row.pending == 5 and row.delivered == 0


def test_exact_fraction_is_not_rounded_up_and_expiry_does_not_cancel_paid_claim():
    small = replace(event(),legs=(EntitlementLeg("ordinary","common","subscription",D("0.3")),))
    book = grant_entitlements(RightsBook(D(100)),"grant",small,5,as_of=EX).book
    assert position(book,"ordinary").entitled == D("1.5")
    payment = terms(book,"ordinary","10")
    with pytest.raises(ValueError,match="pooling is not assumed"):
        subscribe_batch(book,"over",(PaymentRequest(payment,2,D(0)),),as_of=PAY)
    paid = subscribe_batch(book,"one",(PaymentRequest(payment,1,D(0)),),as_of=PAY).book
    with pytest.raises(ValueError,match="history/window"):
        expire_unpaid(paid,"early",payment,as_of="2024-01-05T23:00:00+08:00")
    expired = expire_unpaid(paid,"expiry",payment,as_of="2024-01-06T09:00:00+08:00").book
    row = position(expired,"ordinary")
    assert row.unpaid == 0 and row.expired == D("0.5") and row.pending == 1
    assert row.entitled == row.expired+row.pending and expired.cash == 90


def test_restart_and_verified_idempotency_preserve_all_cash_quantities_and_credits():
    book = granted()
    resumed = decode_book(encode_book(book))
    reference = subscribe_batch(book,"pay",requests(book),as_of=PAY)
    actual = subscribe_batch(resumed,"pay",requests(resumed),as_of=PAY)
    assert actual == reference and decode_book(encode_book(actual.book)) == actual.book
    before = encode_book(actual.book)
    duplicate = subscribe_batch(actual.book,"pay",requests(book),as_of=PAY)
    assert not duplicate.applied and duplicate.cash_delta == 0 and not duplicate.credits
    assert encode_book(duplicate.book) == before
    changed = (replace(requests(book)[0],units=4),requests(book)[1])
    with pytest.raises(ValueError,match="payload changed"):
        subscribe_batch(actual.book,"pay",changed,as_of=PAY)
    assert encode_book(actual.book) == before
    with pytest.raises(ValueError,match="already granted"):
        grant_entitlements(book,"another-key",event(),100,as_of=EX)


def test_exact_cash_and_fraction_survive_a_callers_low_decimal_precision():
    contract = replace(event(),legs=(EntitlementLeg("ordinary","common","subscription",
                                                 D("0.123456789012345678")),))
    with localcontext() as context:
        context.prec = 6
        initial = grant_entitlements(RightsBook(D("10000000000000000.10")),"grant",
                                     contract,10,as_of=EX).book
        paid = subscribe_batch(initial,"pay",(PaymentRequest(terms(initial,"ordinary","58.90"),1,D(0)),),
                               as_of=PAY).book
        restored = decode_book(encode_book(paid))
    assert restored == paid
    assert paid.cash == D("9999999999999941.20")
    assert position(paid,"ordinary").unpaid == D("0.23456789012345678")


def test_later_ratio_revision_changes_only_unconsumed_rights_and_keeps_original_commands():
    book = granted()
    old = encode_book(book)
    updated = replace(event(),available_at="2024-01-03T08:00:00+08:00",evidence_sha256=("c"*64,),
        legs=tuple(replace(leg,units_per_parent=D("0.049")) if leg.leg_id == "ordinary" else leg
                   for leg in event().legs))
    with pytest.raises(ValueError,match="not available"):
        revise_entitlements(book,"future",updated,as_of=EX)
    revised = revise_entitlements(book,"revision",updated,as_of=PAY)
    assert revised.cash_delta == 0 and revised.book.cash == 100
    assert position(revised.book,"ordinary").unpaid == D("4.9")
    assert position(revised.book,"bonus").pending == 10
    assert revised.book.receipts[0] == book.receipts[0] and encode_book(book) == old
    assert not revise_entitlements(revised.book,"revision",updated,as_of=PAY).applied
    assert decode_book(encode_book(revised.book)) == revised.book
    paid = subscribe_batch(book,"pay",requests(book),as_of=PAY).book
    with pytest.raises(ValueError,match="explicit correction"):
        revise_entitlements(paid,"too-late",updated,as_of=PAY)


@pytest.mark.parametrize("change", ["wrong_asset", "over_delivery", "early_date"])
def test_delivery_rejects_wrong_class_excess_or_early_session(change):
    initial = granted()
    paid = subscribe_batch(initial,"pay",requests(initial),as_of=PAY).book
    row = position(paid,"ordinary")
    delivery = DeliveryTerms(row.key,row.leg.asset_key,"receipt", "2024-01-08", "2024-01-09",
                              "2024-01-03T08:00:00+08:00",HASHES,D(0))
    units, stamp = 5, DELIVER
    if change == "wrong_asset":
        delivery = replace(delivery,asset_key="other-class")
    elif change == "over_delivery":
        units = 6
    else:
        stamp = "2024-01-05T09:00:00+08:00"
    before = encode_book(paid)
    with pytest.raises(ValueError):
        deliver_claim(paid,"bad",delivery,units,as_of=stamp)
    assert encode_book(paid) == before
