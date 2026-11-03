"""Full original instruction catalogs survive restart and reject substituted archives."""
import json
from dataclasses import asdict, replace
from decimal import Decimal as D

import pytest
from test_odd_lot_rights_authorization_bridge import two_elections
from test_odd_lot_rights_explicit_authorization import setup
from test_odd_lot_rights_inventory import granted_account
from test_odd_lot_rights_session_flow import _post, _start, _step
from test_odd_lot_rights_transitions import HASHES, PAY, event

from quant_fund_lab.odd_lot_rights.authorization_archive import (
    AuthorizedRightsAccount,
    apply_account_authorization,
    record_account_decline,
)
from quant_fund_lab.odd_lot_rights.authorization_archive_audit import validate_authorization_archive
from quant_fund_lab.odd_lot_rights.authorization_archive_codec import (
    decode_authorized_account,
    encode_authorized_account,
)
from quant_fund_lab.odd_lot_rights.codec import canonical
from quant_fund_lab.odd_lot_rights.inventory import post_rights_transition
from quant_fund_lab.odd_lot_rights.inventory_codec import encode_inventory
from quant_fund_lab.odd_lot_rights.payment_authorization import authorize_subscription
from quant_fund_lab.odd_lot_rights.session_policy import (
    PaymentInterval,
    RightsSessionPolicy,
    SubscriptionElection,
)
from quant_fund_lab.odd_lot_rights.transitions import grant_entitlements, subscribe_batch
from quant_fund_lab.odd_lot_rights.types import EntitlementLeg, PaymentRequest, PaymentTerms


def partial_account():
    book, policy, first, second, intervals = two_elections()
    inventory = granted_account()
    assert inventory.book == book
    account = AuthorizedRightsAccount(inventory, policy)
    authorization = authorize_subscription(policy, "pay-a", first, intervals[:1], as_of=PAY)
    return apply_account_authorization(account, authorization), authorization, second, intervals[1:]


def test_entire_catalog_and_each_original_authorization_roundtrip_with_the_inventory():
    account, first, second, intervals = partial_account()
    assert account.inventory.cash == 90
    original = encode_authorized_account(account)
    payload = json.loads(original)
    assert len(payload["policy"]["elections"]) == 2 and len(payload["authorizations"]) == 1
    account = decode_authorized_account(original)
    authorization = authorize_subscription(account.policy, "pay-b", second, intervals,
                                           as_of="2024-01-03T09:01:00+08:00")
    complete = apply_account_authorization(account, authorization)
    assert complete.inventory.cash == 70 and len(complete.authorizations) == 2
    assert decode_authorized_account(encode_authorized_account(complete)) == complete
    assert apply_account_authorization(complete, first) is complete
    assert apply_account_authorization(complete, authorization) is complete
    assert encode_authorized_account(account) == original


def test_retry_uses_archived_original_not_a_caller_relabelled_authorization():
    account, first, _, _ = partial_account()
    changed = replace(first, intervals=(replace(first.intervals[0], available_at="2024-01-03T08:01:00+08:00"),))
    before = encode_authorized_account(account)
    with pytest.raises(ValueError, match="recorded authorization"):
        apply_account_authorization(account, changed)
    assert encode_authorized_account(account) == before


@pytest.mark.parametrize("change", ["missing", "duplicate", "unused_fee", "future_unused_terms", "interval", "request", "float_fee", "action_order", "schema", "duplicate_json"])
def test_archive_rejects_missing_or_substituted_full_catalog_even_when_inventory_is_valid(change):
    account, _, _, _ = partial_account()
    payload = json.loads(encode_authorized_account(account))
    original_inventory = payload["inventory"]
    if change == "missing":
        payload["authorizations"] = []
    elif change == "duplicate":
        payload["authorizations"] *= 2
    elif change in {"unused_fee", "future_unused_terms", "float_fee", "action_order"}:
        if change == "action_order":
            payload["policy"]["elections"].reverse()
        else:
            request = payload["policy"]["elections"][1]["requests"][0]
            if change == "future_unused_terms":
                request["terms"]["available_at"] = "2024-01-04T08:00:00+08:00"
            else:
                request["fee"] = 0.0 if change == "float_fee" else "1"
        payload["authorizations"][0]["policy"] = payload["policy"]
    elif change == "interval":
        payload["authorizations"][0]["intervals"][0]["available_at"] = "2024-01-03T08:01:00+08:00"
    elif change == "request":
        payload["authorizations"][0]["requests"][0]["units"] = 2
    elif change == "schema":
        payload["schema_version"] = True
    encoded = canonical(payload)
    if change == "duplicate_json":
        encoded = encoded.replace('"schema_version":1', '"schema_version":1,"schema_version":1', 1)
    assert payload["inventory"] == original_inventory
    with pytest.raises((ValueError, TypeError)):
        decode_authorized_account(encoded)
    assert encode_inventory(account.inventory) == original_inventory


def test_legacy_bare_payment_can_be_archived_and_replayed_without_rewriting_inventory():
    book, batch, policy, intervals = setup()
    authorization = authorize_subscription(policy, "pay", batch, intervals, as_of=PAY)
    inventory = post_rights_transition(granted_account(), subscribe_batch(book, "pay", batch, as_of=PAY))
    before = encode_inventory(inventory)
    account = AuthorizedRightsAccount(inventory, policy, (authorization,))
    restored = decode_authorized_account(encode_authorized_account(account))
    assert encode_inventory(restored.inventory) == before
    assert apply_account_authorization(restored, authorization) is restored


def test_independent_archive_validation_never_calls_production_policy_or_payment(monkeypatch):
    from quant_fund_lab.odd_lot_rights import payment_authorization, policy_election, session_policy

    account, _, _, _ = partial_account()
    def forbidden(*args, **kwargs):
        raise AssertionError("production constructor/payment used by independent archive verifier")
    monkeypatch.setattr(payment_authorization.PaymentAuthorization, "__post_init__", forbidden)
    monkeypatch.setattr(session_policy.RightsSessionPolicy, "__post_init__", forbidden)
    monkeypatch.setattr(payment_authorization, "apply_authorized_subscription", forbidden)
    monkeypatch.setattr(policy_election, "elect_subscription", forbidden)
    validate_authorization_archive(json.loads(canonical(asdict(account.policy))),
        json.loads(canonical([asdict(row) for row in account.authorizations])), account.inventory.book.receipts)


def test_an_unexecuted_future_election_is_preserved_but_not_implicitly_executed():
    account, _, _, _ = partial_account()
    restored = decode_authorized_account(encode_authorized_account(account))
    assert len(restored.policy.elections) == 2 and len(restored.authorizations) == 1
    assert restored.inventory.cash == D(90)
    assert restored.inventory.book.receipts[-1].action_id == "pay-a"


def test_unlisted_decline_archives_without_consuming_claims_or_payment_authorizations():
    account, _, _, _ = partial_account()
    key = account.inventory.book.positions[1].key
    declined = record_account_decline(account, "unlisted", (key,), as_of="2024-01-03T10:00:00+08:00")
    assert declined.inventory.cash == 90 and declined.authorizations == account.authorizations
    assert declined.inventory.book.positions == account.inventory.book.positions
    restored = decode_authorized_account(encode_authorized_account(declined))
    assert restored == declined
    assert record_account_decline(restored, "unlisted", (key,), as_of="2024-01-03T10:00:00+08:00") is restored
    with pytest.raises(ValueError, match="override a frozen selected payment"):
        record_account_decline(account, "pay-b", (key,), as_of="2024-01-03T10:00:00+08:00")


def test_actual_tplus2_sessions_restart_full_archive_and_never_spend_future_cash(monkeypatch):
    data, research, config, runtime, inventory = _start(monkeypatch)
    inputs, result = _step(data, research, config, runtime, 29)
    inventory = _post(inventory, inputs, result)
    first, due = (str(data.close.index[index].date()) for index in (30, 33))
    contract = replace(event(), parent_security_id="2330.TW", ex_session=first,
        available_at=first+"T08:00:00+08:00",
        legs=(EntitlementLeg("paid", "new-share-class", "subscription", D(1)),))
    inventory = post_rights_transition(inventory, grant_entitlements(inventory.book, "grant", contract, 3,
                                       as_of=first+"T16:01:00+08:00"))
    terms = PaymentTerms(inventory.book.positions[0].key, D(10), first, due,
                         first+"T08:00:00+08:00", HASHES)
    batch = (PaymentRequest(terms, 1, D(0)),)
    policy = RightsSessionPolicy(1, "Asia/Taipei", first+"T16:02:00+08:00",
        (SubscriptionElection("pay", batch),), "usable_cash_only_atomic", "do_not_subscribe")
    intervals = (PaymentInterval(terms.right_key, due+"T09:00:00+08:00",
        due+"T17:00:00+08:00", first+"T08:00:00+08:00", HASHES),)
    account = AuthorizedRightsAccount(inventory, policy)
    early = authorize_subscription(policy, "pay", batch, intervals, as_of=due+"T14:00:00+08:00")
    runtime = result.runtime
    for index in range(30, 33):
        inputs, result = _step(data, research, config, runtime, index)
        if index == 32:
            before = encode_authorized_account(account)
            with pytest.raises(ValueError, match="insufficient usable cash"):
                apply_account_authorization(account, early)
            assert encode_authorized_account(account) == before
        account = replace(account, inventory=_post(account.inventory, inputs, result))
        account = decode_authorized_account(encode_authorized_account(account))
        runtime = result.runtime
    assert account.inventory.cash == 300 and not account.authorizations
    with pytest.raises(ValueError, match="completed clock"):
        apply_account_authorization(account, early)
    now = authorize_subscription(policy, "pay", batch, intervals, as_of=due+"T16:01:00+08:00")
    paid = apply_account_authorization(account, now)
    assert paid.inventory.cash == 290 and paid.authorizations == (now,)
    assert decode_authorized_account(encode_authorized_account(paid)) == paid
