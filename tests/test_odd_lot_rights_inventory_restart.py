"""Joined checkpoints preserve every transition and reject altered inventory/anchors."""
import json
from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_odd_lot_rights_inventory import account, delivery, paid_account
from test_odd_lot_rights_transitions import DELIVER, EX, PAY, event, requests

from quant_fund_lab.odd_lot_rights.codec import canonical
from quant_fund_lab.odd_lot_rights.inventory import post_rights_transition
from quant_fund_lab.odd_lot_rights.inventory_codec import decode_inventory, encode_inventory
from quant_fund_lab.odd_lot_rights.transitions import (
    deliver_claim,
    grant_entitlements,
    subscribe_batch,
)


def sequence(current, restart):
    checkpoints = []
    result = grant_entitlements(current.book,"grant",event(),100,as_of=EX)
    current = post_rights_transition(current,result)
    checkpoints.append(encode_inventory(current))
    if restart:
        current = decode_inventory(checkpoints[-1])
    result = subscribe_batch(current.book,"pay",requests(current.book),as_of=PAY)
    current = post_rights_transition(current,result)
    checkpoints.append(encode_inventory(current))
    if restart:
        current = decode_inventory(checkpoints[-1])
    for leg,units in (("bonus",10),("ordinary",5),("preferred",2)):
        terms = delivery(current,leg,units)
        result = deliver_claim(current.book,"deliver-"+leg,terms,units,as_of=DELIVER)
        current = post_rights_transition(current,result)
        checkpoints.append(encode_inventory(current))
        if restart:
            current = decode_inventory(checkpoints[-1])
    return current,checkpoints


def test_restart_after_every_boundary_matches_every_cash_lot_posting_and_command():
    full,full_frames = sequence(account(),False)
    resumed,resumed_frames = sequence(account(),True)
    assert full == resumed and full_frames == resumed_frames
    assert resumed.cash == D(10) and len(resumed.postings) == 3
    terms = delivery(resumed,"preferred",2)
    result = deliver_claim(resumed.book,"deliver-preferred",terms,2,as_of=DELIVER)
    assert post_rights_transition(resumed,result) is resumed


@pytest.mark.parametrize("mutation", ["quantity","tradability","anchor","posting","float_anchor","schema","duplicate_key"])
def test_joined_checkpoint_rejects_changed_inventory_or_financial_evidence(mutation):
    current,_ = sequence(account(),True)
    payload = encode_inventory(current)
    values = json.loads(payload)
    if mutation == "quantity":
        values["lots"][0]["units"] += 1
    elif mutation == "tradability":
        values["lots"][0]["tradable_session"] = "2024-01-08"
    elif mutation == "anchor":
        values["initial_cash"] = "101"
    elif mutation == "posting":
        values["postings"] = values["postings"][:-1]
    elif mutation == "float_anchor":
        values["initial_cash"] = 100.
    elif mutation == "schema":
        values["schema_version"] = True
    else:
        payload = payload.replace('"schema_version":1','"schema_version":1,"schema_version":1')
    if mutation != "duplicate_key":
        payload = canonical(values)
    with pytest.raises((ValueError,TypeError)):
        decode_inventory(payload)


def test_held_lot_from_a_different_leg_cannot_cover_a_receipt_debit():
    # Constructor must rederive owned lots, not just accept matching aggregate quantities.
    current = paid_account()
    result = deliver_claim(current.book,"deliver",delivery(current,"ordinary",5),5,as_of=DELIVER)
    current = post_rights_transition(current,result)
    lots = tuple(replace(row,right_key="another-entitlement") if row.security_id == "ordinary-security" else row
                 for row in current.lots)
    with pytest.raises(ValueError,match="owned inventory differs"):
        replace(current,lots=tuple(sorted(lots,key=lambda row:(row.right_key,row.security_id,row.tradable_session))))


def test_joined_constructor_cannot_bypass_pre_event_ownership_validation():
    current = account()
    forged = grant_entitlements(current.book,"grant",event(),101,as_of=EX)
    with pytest.raises(ValueError,match="original grant ownership"):
        replace(current,book=forged.book)


def test_later_entitlement_basis_uses_delivered_inventory_at_that_exact_command():
    from test_odd_lot_rights_transitions import HASHES

    current = paid_account()
    current = post_rights_transition(current,deliver_claim(current.book,"deliver",
        delivery(current,"ordinary",5),5,as_of=DELIVER))
    later = replace(event(),event_id="d"*64,parent_security_id="ordinary-security",
        ex_session="2024-01-10",available_at="2024-01-09T08:00:00+08:00",evidence_sha256=HASHES)
    result = grant_entitlements(current.book,"later-grant",later,5,as_of="2024-01-10T08:00:00+08:00")
    after = post_rights_transition(current,result)
    assert decode_inventory(encode_inventory(after)) == after
    assert len(after.book.positions) == 6
