"""Later net payouts and receipt exchange consume claims instead of minting assets."""
from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_odd_lot_rights_transitions import (
    DELIVER,
    EX,
    HASHES,
    PAY,
    event,
    granted,
    position,
    requests,
)

from quant_fund_lab.odd_lot_rights.codec import decode_book, encode_book
from quant_fund_lab.odd_lot_rights.settlement import (
    FractionalCashTerms,
    ReceiptConversionTerms,
    convert_receipt,
    settle_fraction,
)
from quant_fund_lab.odd_lot_rights.transitions import (
    deliver_claim,
    grant_entitlements,
    subscribe_batch,
)
from quant_fund_lab.odd_lot_rights.types import DeliveryTerms, EntitlementLeg, RightsBook
from quant_fund_lab.odd_lot_rights.valuation import RightsMark, value_book


def test_fractional_cash_uses_later_documented_net_amount_once_not_an_assumed_sale_price():
    bonus = replace(event(),legs=(EntitlementLeg("bonus","bonus-class","bonus",D("0.1")),))
    book = grant_entitlements(RightsBook(D(100)),"grant",bonus,15,as_of=EX).book
    row = book.positions[0]
    assert row.pending == 1 and row.unpaid == D("0.5")
    terms = FractionalCashTerms(row.key,D("0.5"),D(8),"2024-01-09",
        "2024-01-09T08:00:00+08:00",HASHES)
    with pytest.raises(ValueError,match="not available"):
        settle_fraction(book,"too-early",terms,as_of=DELIVER)
    stamp = "2024-01-09T09:00:00+08:00"
    result = settle_fraction(decode_book(encode_book(book)),"cash",terms,as_of=stamp)
    assert result.cash_delta == 8 and result.book.cash == 108
    updated = result.book.positions[0]
    assert updated.unpaid == 0 and updated.settled_fraction == D("0.5") and updated.pending == 1
    mark = RightsMark(row.key,"pending",D(20),"2024-01-09",terms.available_at,HASHES)
    assert value_book(result.book,(mark,),as_of=stamp).total_book_value == 128
    before = encode_book(result.book)
    duplicate = settle_fraction(result.book,"cash",terms,as_of=stamp)
    assert not duplicate.applied and duplicate.cash_delta == 0
    assert encode_book(duplicate.book) == before
    with pytest.raises(ValueError,match="outstanding bonus claim"):
        settle_fraction(result.book,"different-key",terms,as_of=stamp)
    assert book.cash == 100 and book.positions[0].unpaid == D("0.5")


def receipt_book():
    initial = granted()
    paid = subscribe_batch(initial,"pay",requests(initial),as_of=PAY).book
    row = position(paid,"ordinary")
    terms = DeliveryTerms(row.key,row.leg.asset_key,"ordinary-receipt", "2024-01-08", "2024-01-08",
                          "2024-01-05T08:00:00+08:00",HASHES,D(0))
    return deliver_claim(paid,"delivery",terms,5,as_of=DELIVER).book


def conversion(book):
    row = position(book,"ordinary")
    return ReceiptConversionTerms(row.key,row.leg.asset_key,"ordinary-receipt","ordinary-final",
        "2024-01-10","2024-01-11","2024-01-09T08:00:00+08:00",HASHES,D(0))


def test_conversion_uses_actual_remaining_receipts_and_has_equal_debit_credit():
    book = receipt_book()
    terms = conversion(book)
    with pytest.raises(ValueError,match="not available"):
        convert_receipt(book,"early",terms,3,as_of=DELIVER)
    # Outer inventory sold two of the five receipts earlier; only three remain.
    result = convert_receipt(decode_book(encode_book(book)),"convert",terms,3,
                             as_of="2024-01-10T09:00:00+08:00")
    assert result.debits[0].security_id == "ordinary-receipt" and result.debits[0].units == 3
    assert result.credits[0].security_id == "ordinary-final" and result.credits[0].units == 3
    assert result.credits[0].tradable_session == "2024-01-11"
    assert result.cash_delta == 0 and result.book.cash == book.cash
    assert position(result.book,"ordinary").delivered == 5
    duplicate = convert_receipt(result.book,"convert",terms,3,as_of="2024-01-10T09:00:00+08:00")
    assert not duplicate.applied and not duplicate.credits and not duplicate.debits
    with pytest.raises(ValueError,match="exceeds delivered"):
        convert_receipt(result.book,"another",terms,3,as_of="2024-01-10T09:00:00+08:00")


def test_delivery_and_conversion_fees_are_explicit_cash_costs():
    initial = granted()
    paid = subscribe_batch(initial,"pay",requests(initial),as_of=PAY).book
    row = position(paid,"ordinary")
    delivery = DeliveryTerms(row.key,row.leg.asset_key,"ordinary-receipt", "2024-01-08", "2024-01-08",
                              "2024-01-05T08:00:00+08:00",HASHES,D(2))
    delivered = deliver_claim(paid,"delivery",delivery,5,as_of=DELIVER)
    assert delivered.book.cash == 8 and delivered.cash_delta == -2
    assert position(delivered.book,"ordinary").fees_paid == 2
    converted = convert_receipt(delivered.book,"convert",replace(conversion(delivered.book),fee=D("1.5")),5,
                                as_of="2024-01-10T09:00:00+08:00")
    assert converted.book.cash == D("6.5") and converted.cash_delta == D("-1.5")
    assert position(converted.book,"ordinary").fees_paid == D("3.5")
    assert converted.credits[0].units == converted.debits[0].units == 5
    assert decode_book(encode_book(converted.book)) == converted.book


@pytest.mark.parametrize("operation", ["delivery", "conversion"])
def test_asset_changes_are_rejected_when_explicit_service_fees_exceed_usable_cash(operation):
    if operation == "delivery":
        initial = granted()
        book = subscribe_batch(initial,"pay",requests(initial),as_of=PAY).book
        row = position(book,"ordinary")
        contract = DeliveryTerms(row.key,row.leg.asset_key,"ordinary-receipt", "2024-01-08", "2024-01-08",
                                 "2024-01-05T08:00:00+08:00",HASHES,D(100))
        def run():
            return deliver_claim(book,"delivery",contract,5,as_of=DELIVER)
    else:
        book = receipt_book()
        def run():
            return convert_receipt(book,"conversion",replace(conversion(book),fee=D(100)),5,
                                    as_of="2024-01-10T09:00:00+08:00")
    before = encode_book(book)
    with pytest.raises(ValueError,match="insufficient usable cash"):
        run()
    assert encode_book(book) == before


@pytest.mark.parametrize("change", ["wrong_receipt", "wrong_asset", "over_quantity", "before_conversion"])
def test_conversion_cannot_use_unrelated_or_not_yet_deliverable_inventory(change):
    book = receipt_book()
    terms, units, stamp = conversion(book), 5, "2024-01-10T09:00:00+08:00"
    if change == "wrong_receipt":
        terms = replace(terms,receipt_security_id="other-receipt")
    elif change == "wrong_asset":
        terms = replace(terms,asset_key="preferred-class")
    elif change == "over_quantity":
        units = 6
    else:
        stamp = "2024-01-09T09:00:00+08:00"
    before = encode_book(book)
    with pytest.raises(ValueError):
        convert_receipt(book,"invalid",terms,units,as_of=stamp)
    assert encode_book(book) == before
