"""Joined cash/rights/security posting never doubles assets or releases units early."""
from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_odd_lot_rights_transitions import (
    DELIVER,
    EX,
    HASHES,
    PAY,
    event,
    marks,
    position,
    requests,
)

from quant_fund_lab.odd_lot_rights.codec import encode_book
from quant_fund_lab.odd_lot_rights.inventory import (
    RightsInventory,
    SecurityLot,
    post_rights_transition,
)
from quant_fund_lab.odd_lot_rights.inventory_valuation import SecurityMark, value_inventory
from quant_fund_lab.odd_lot_rights.settlement import ReceiptConversionTerms, convert_receipt
from quant_fund_lab.odd_lot_rights.transitions import (
    deliver_claim,
    grant_entitlements,
    subscribe_batch,
)
from quant_fund_lab.odd_lot_rights.types import DeliveryTerms, RightsBook, SecurityCredit


def account():
    original = (SecurityLot("opening-inventory","parent-security",100,"2023-12-01"),)
    return RightsInventory(D(100),original,RightsBook(D(100)),original)


def granted_account():
    original = account()
    return post_rights_transition(original,grant_entitlements(original.book,"grant",event(),100,as_of=EX))


def paid_account():
    original = granted_account()
    return post_rights_transition(original,subscribe_batch(original.book,"pay",requests(original.book),as_of=PAY))


def delivery(account,leg,units):
    row = position(account.book,leg)
    return DeliveryTerms(row.key,row.leg.asset_key,leg+"-security","2024-01-08","2024-01-09",
                         "2024-01-05T08:00:00+08:00",HASHES,D(0))


def test_joint_posting_values_cash_pending_and_delivered_inventory_exactly_once():
    current = granted_account()
    parent = SecurityMark("parent-security",D(1),"2024-01-02",EX,HASHES)
    assert value_inventory(current,(parent,),marks(current.book,"2024-01-02",after_payment=False),as_of=EX).nav == 460
    current = post_rights_transition(current,subscribe_batch(current.book,"pay",requests(current.book),as_of=PAY))
    assert current.cash == 10
    assert value_inventory(current,(replace(parent,session="2024-01-03"),),
        marks(current.book,"2024-01-03",after_payment=True),as_of=PAY).nav == 460
    security_marks = [replace(parent,session="2024-01-08")]
    for leg,units,price in (("bonus",10,20),("ordinary",5,20),("preferred",2,25)):
        before = current
        terms = delivery(current,leg,units)
        result = deliver_claim(current.book,"deliver-"+leg,terms,units,as_of=DELIVER)
        current = post_rights_transition(current,result)
        assert current.cash == 10 and current.tradable_units(leg+"-security","2024-01-08") == 0
        assert current.tradable_units(leg+"-security","2024-01-09") == units
        security_marks.append(SecurityMark(leg+"-security",D(price),"2024-01-08",DELIVER,HASHES))
        nav = value_inventory(current,tuple(security_marks),marks(current.book,"2024-01-08",after_payment=True),as_of=DELIVER)
        assert nav.nav == 460 and nav.cash == 10
        assert post_rights_transition(before,result) == current
        replay = deliver_claim(current.book,"deliver-"+leg,terms,units,as_of=DELIVER)
        assert post_rights_transition(current,replay) is current
    assert len(current.postings) == 3 and len(current.lots) == 4
    assert current.book.positions[0].pending == 0


@pytest.mark.parametrize("mutation", ["cash_delta","credit_units","credit_security","credit_date","missing_credit"])
def test_forged_transition_outputs_are_rejected_before_any_cash_or_inventory_posting(mutation):
    current = paid_account()
    terms = delivery(current,"ordinary",5)
    result = deliver_claim(current.book,"deliver",terms,5,as_of=DELIVER)
    if mutation == "cash_delta":
        result = replace(result,cash_delta=D(1))
    elif mutation == "missing_credit":
        result = replace(result,credits=())
    else:
        credit = result.credits[0]
        values = {"credit_units":{"units":6},"credit_security":{"security_id":"other"},
                  "credit_date":{"tradable_session":"2024-01-08"}}[mutation]
        result = replace(result,credits=(replace(credit,**values),))
    before = encode_book(current.book),current.lots,current.postings
    with pytest.raises(ValueError):
        post_rights_transition(current,result)
    assert (encode_book(current.book),current.lots,current.postings) == before


def test_grant_uses_actual_pre_event_ownership_and_cannot_skip_a_command_prefix():
    current = account()
    with pytest.raises(ValueError,match="ownership"):
        post_rights_transition(current,grant_entitlements(current.book,"grant",event(),101,as_of=EX))
    granted = grant_entitlements(current.book,"grant",event(),100,as_of=EX)
    paid = subscribe_batch(granted.book,"pay",requests(granted.book),as_of=PAY)
    with pytest.raises(ValueError,match="prefix"):
        post_rights_transition(current,paid)
    assert current.book == RightsBook(D(100)) and len(current.lots) == 1


def test_inventory_conversion_consumes_receipts_and_cannot_mint_replacement_units():
    current = paid_account()
    terms = delivery(current,"ordinary",5)
    current = post_rights_transition(current,deliver_claim(current.book,"deliver",terms,5,as_of=DELIVER))
    row = position(current.book,"ordinary")
    conversion = ReceiptConversionTerms(row.key,row.leg.asset_key,"ordinary-security","final-security",
        "2024-01-10","2024-01-11","2024-01-09T08:00:00+08:00",HASHES,D(1))
    result = convert_receipt(current.book,"convert",conversion,5,as_of="2024-01-10T09:00:00+08:00")
    converted = post_rights_transition(current,result)
    assert converted.cash == 9
    assert converted.tradable_units("ordinary-security","2024-01-10") == 0
    assert converted.tradable_units("final-security","2024-01-10") == 0
    assert converted.tradable_units("final-security","2024-01-11") == 5
    assert not any(lot.security_id == "ordinary-security" for lot in converted.lots)
    with pytest.raises(ValueError,match="prefix"):
        post_rights_transition(converted,result)


@pytest.mark.parametrize("mutation", ["lot_quantity","lost_posting","tradability"])
def test_account_reconstruction_refuses_forged_inventory_even_with_valid_book(mutation):
    current = paid_account()
    result = deliver_claim(current.book,"deliver",delivery(current,"ordinary",5),5,as_of=DELIVER)
    current = post_rights_transition(current,result)
    if mutation == "lost_posting":
        values = {"postings":()}
    else:
        lots = list(current.lots)
        index = next(i for i,row in enumerate(lots) if row.security_id == "ordinary-security")
        lots[index] = replace(lots[index],**({"units":6} if mutation == "lot_quantity" else {"tradable_session":"2024-01-08"}))
        values = {"lots":tuple(lots)}
    with pytest.raises(ValueError):
        replace(current,**values)


def test_noop_output_cannot_add_cash_or_credits_and_past_holdings_query_rejected():
    current = granted_account()
    result = grant_entitlements(current.book,"grant",event(),100,as_of=EX)
    forged = replace(result,credits=(SecurityCredit(current.book.positions[0].key,"fake",1,"2024-01-02"),))
    with pytest.raises(ValueError,match="no-op"):
        post_rights_transition(current,forged)
    with pytest.raises(ValueError,match="past session"):
        current.tradable_units("parent-security","2024-01-01")


def test_missing_delivered_asset_mark_cannot_disappear_from_nav():
    current = paid_account()
    current = post_rights_transition(current,deliver_claim(current.book,"deliver",
        delivery(current,"ordinary",5),5,as_of=DELIVER))
    parent = SecurityMark("parent-security",D(1),"2024-01-08",DELIVER,HASHES)
    with pytest.raises(ValueError,match="marks are missing"):
        value_inventory(current,(parent,),marks(current.book,"2024-01-08",after_payment=True),as_of=DELIVER)


@pytest.mark.parametrize("mutation", ["future","stale","duplicate","unrelated"])
def test_delivered_nontradable_assets_still_require_current_known_unique_marks(mutation):
    current = paid_account()
    current = post_rights_transition(current,deliver_claim(current.book,"deliver",
        delivery(current,"ordinary",5),5,as_of=DELIVER))
    parent = SecurityMark("parent-security",D(1),"2024-01-08",DELIVER,HASHES)
    delivered = SecurityMark("ordinary-security",D(20),"2024-01-08",DELIVER,HASHES)
    if mutation == "future":
        values = (parent,replace(delivered,available_at="2024-01-09T08:00:00+08:00"))
    elif mutation == "stale":
        values = (parent,replace(delivered,session="2024-01-07"))
    elif mutation == "duplicate":
        values = (parent,delivered,delivered)
    else:
        values = (parent,replace(delivered,security_id="another"))
    with pytest.raises(ValueError):
        value_inventory(current,values,marks(current.book,"2024-01-08",after_payment=True),as_of=DELIVER)
