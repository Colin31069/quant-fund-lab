"""Explicit policy elections bind cutoffs without auto-funding or implicit priority."""
import json
from dataclasses import replace
from decimal import Decimal as D
from decimal import localcontext

import pytest
from test_odd_lot_rights_inventory import granted_account
from test_odd_lot_rights_session_projection import funded
from test_odd_lot_rights_transitions import HASHES, PAY, requests

from quant_fund_lab.odd_lot_rights.audit import audit_rights
from quant_fund_lab.odd_lot_rights.codec import canonical, fingerprint
from quant_fund_lab.odd_lot_rights.inventory import post_rights_transition
from quant_fund_lab.odd_lot_rights.inventory_codec import decode_inventory, encode_inventory
from quant_fund_lab.odd_lot_rights.payment_policy import PaymentCutoff, RightsParticipationPolicy
from quant_fund_lab.odd_lot_rights.policy_election import elect_subscription
from quant_fund_lab.odd_lot_rights.transitions import subscribe_batch
from quant_fund_lab.odd_lot_rights.types import ActionReceipt, PaymentRequest, PaymentTerms


def policy(**changes):
    return replace(RightsParticipationPolicy("explicit-fixture", "2024-01-01T08:00:00+08:00",
        "explicit_election", "reject_batch", "retain_until_evidenced", "explicit_current_marks",
        "already_usable", "inclusive"), **changes)


def windows(rows, day="2024-01-03", cutoff="14:00:00"):
    return tuple(PaymentCutoff(row.terms.right_key, day+"T09:00:00+08:00",
        day+"T"+cutoff+"+08:00", day+"T08:00:00+08:00", HASHES) for row in rows)


def election(account, *, stamp=PAY, rule=None, payment=None, cutoffs=None, action="election"):
    payment = requests(account.book) if payment is None else payment
    return elect_subscription(account.book, action, rule or policy(),
        tuple(row.terms.right_key for row in payment), payment,
        windows(payment) if cutoffs is None else cutoffs, as_of=stamp, decision="pay")


def test_policy_election_one_original_receipt_exact_batch_and_restart_noop():
    account = granted_account()
    paid = post_rights_transition(account, election(account))
    assert paid.cash == 10 and len(paid.book.receipts) == 2
    command = json.loads(paid.book.receipts[-1].command_json)
    assert command["kind"] == "policy_election" and command["terms"]["policy_id"] == policy().policy_id
    assert sum(row.cash_paid for row in paid.book.positions) == 90
    assert decode_inventory(encode_inventory(paid)) == paid
    replay = elect_subscription(paid.book, "election", policy(),
        tuple(row.terms.right_key for row in requests(account.book)), requests(account.book),
        windows(requests(account.book)), as_of=PAY, decision="pay")
    assert post_rights_transition(paid, replay) is paid
    with pytest.raises(ValueError, match="payload changed"):
        elect_subscription(paid.book, "election", policy(cutoff_boundary="exclusive"),
            tuple(row.terms.right_key for row in requests(account.book)), requests(account.book),
            windows(requests(account.book)), as_of=PAY, decision="pay")


def test_decline_records_choice_without_expiring_unpaid_or_removing_paid_claims():
    account = granted_account()
    chosen = (replace(requests(account.book)[0], units=1),)
    paid = post_rights_transition(account, election(account, payment=chosen))
    key = chosen[0].terms.right_key
    result = elect_subscription(paid.book, "decline", policy(),
        (key,), (), (), as_of="2024-01-03T10:00:00+08:00", decision="decline")
    declined = post_rights_transition(paid, result)
    assert declined.cash == 90 and declined.book.positions == paid.book.positions
    assert audit_rights(declined.book, initial_cash=D(100)).passed
    assert decode_inventory(encode_inventory(declined)) == declined


@pytest.mark.parametrize("boundary,accepted", [("inclusive", True), ("exclusive", False)])
def test_exact_cutoff_boundary_is_explicit_and_changes_policy_identity(boundary, accepted):
    account = granted_account()
    rule = policy(cutoff_boundary=boundary)
    assert (rule.policy_id == policy().policy_id) == (boundary == "inclusive")
    if accepted:
        assert election(account, rule=rule, stamp="2024-01-03T14:00:00+08:00").book.cash == 10
    else:
        with pytest.raises(ValueError, match="daily cutoff"):
            election(account, rule=rule, stamp="2024-01-03T14:00:00+08:00")


@pytest.mark.parametrize("change", ["before_open", "after_cutoff", "future_policy", "future_cutoff", "missing_cutoff", "decline_pays"])
def test_unknown_late_or_conflicting_elections_fail_without_state_change(change):
    account = granted_account()
    stamp, rule, cutoffs = PAY, policy(), windows(requests(account.book))
    if change == "before_open":
        stamp = "2024-01-03T08:59:00+08:00"
    elif change == "after_cutoff":
        stamp = "2024-01-03T14:00:01+08:00"
    elif change == "future_policy":
        rule = policy(frozen_at="2024-01-03T10:00:00+08:00")
    elif change == "future_cutoff":
        cutoffs = (replace(cutoffs[0], available_at="2024-01-03T10:00:00+08:00"), cutoffs[1])
    elif change == "missing_cutoff":
        cutoffs = cutoffs[:-1]
    else:
        rule = policy(participation="decline_all")
    before = encode_inventory(account)
    with pytest.raises(ValueError):
        election(account, stamp=stamp, rule=rule, cutoffs=cutoffs)
    assert encode_inventory(account) == before


def test_insufficient_cash_rejects_complete_policy_batch_without_prorating():
    account = granted_account()
    account = replace(account, initial_cash=D(89), book=replace(account.book, cash=D(89)))
    before = encode_inventory(account)
    with pytest.raises(ValueError, match="insufficient usable cash"):
        election(account)
    assert encode_inventory(account) == before


def test_actual_tplus2_close_cash_cannot_fund_earlier_same_day_cutoff(monkeypatch):
    _, _, _, _, account, day = funded(monkeypatch)
    key = account.book.positions[0].key
    payment = (PaymentRequest(PaymentTerms(key, D(10), day, day,
        day+"T08:00:00+08:00", HASHES), 1, D(0)),)
    before = encode_inventory(account)
    with pytest.raises(ValueError, match="daily cutoff"):
        election(account, payment=payment, cutoffs=windows(payment, day),
                 stamp=day+"T16:02:00+08:00")
    with pytest.raises(ValueError, match="completed clock"):
        election(account, payment=payment, cutoffs=windows(payment, day),
                 stamp=day+"T14:00:00+08:00")
    assert encode_inventory(account) == before
    paid = post_rights_transition(account, election(account, payment=payment,
        cutoffs=windows(payment, day, "17:00:00"), stamp=day+"T16:02:00+08:00"))
    assert paid.cash == 280 and audit_rights(paid.book, initial_cash=D(300)).passed


def test_independent_policy_audit_never_calls_production_authorization(monkeypatch):
    from quant_fund_lab.odd_lot_rights import policy_election, transitions

    account = granted_account()
    paid = post_rights_transition(account, election(account))
    def forbidden(*args, **kwargs):
        raise AssertionError("production election/payment authorization called by independent audit")
    monkeypatch.setattr(policy_election, "elect_subscription", forbidden)
    monkeypatch.setattr(policy_election, "subscribe_batch", forbidden)
    monkeypatch.setattr(transitions, "subscribe_batch", forbidden)
    monkeypatch.setattr(RightsParticipationPolicy, "__post_init__", forbidden)
    assert audit_rights(paid.book, initial_cash=D(100)).passed


@pytest.mark.parametrize("change", ["cutoff", "policy_id", "fractional_rule", "decline_mode"])
def test_rehashed_policy_commands_still_require_independent_authorization(change):
    paid = post_rights_transition(granted_account(), election(granted_account()))
    command = json.loads(paid.book.receipts[-1].command_json)
    terms = command["terms"]
    if change == "cutoff":
        terms["cutoffs"][0]["cutoff_at"] = "2024-01-03T08:59:00+08:00"
    elif change == "policy_id":
        terms["policy_id"] = "c"*64
    else:
        terms["policy"]["fractional_rights" if change == "fractional_rule" else "participation"] = (
            "pool_and_round" if change == "fractional_rule" else "decline_all")
        terms["policy_id"] = fingerprint(terms["policy"])
    receipt = ActionReceipt("election", fingerprint(command), canonical(command))
    forged = replace(paid.book, receipts=(*paid.book.receipts[:-1], receipt))
    assert not audit_rights(forged, initial_cash=D(100)).passed
    with pytest.raises(ValueError, match="audit"):
        replace(paid, book=forged)


def test_policy_wrapper_preserves_exact_delta_under_low_caller_decimal_precision():
    account = granted_account()
    initial = D("10000000000000.10")
    account = replace(account, initial_cash=initial, book=replace(account.book, cash=initial))
    payment = tuple(replace(row, fee=D("0.123456789")) for row in requests(account.book))
    with localcontext() as context:
        context.prec = 6
        transition = election(account, payment=payment)
        paid = post_rights_transition(account, transition)
    assert transition.cash_delta == D("-90.246913578")
    assert paid.cash == D("9999999999909.853086422")
    assert decode_inventory(encode_inventory(paid)) == paid


def test_account_cannot_change_frozen_policy_or_bypass_it_with_legacy_payment():
    account = granted_account()
    chosen = (replace(requests(account.book)[0], units=1),)
    paid = post_rights_transition(account, election(account, payment=chosen))
    before = encode_inventory(paid)
    with pytest.raises(ValueError, match="frozen policy"):
        election(paid, payment=chosen, rule=policy(cutoff_boundary="exclusive"),
                 action="changed-policy", stamp="2024-01-03T10:00:00+08:00")
    bypass = subscribe_batch(paid.book, "bare-pay", chosen, as_of="2024-01-03T10:00:00+08:00")
    assert not audit_rights(bypass.book, initial_cash=D(100)).passed
    with pytest.raises(ValueError, match="audit"):
        post_rights_transition(paid, bypass)
    assert encode_inventory(paid) == before


def test_decline_all_policy_records_explicit_decline_without_payment():
    account = granted_account()
    keys = tuple(row.terms.right_key for row in requests(account.book))
    result = elect_subscription(account.book, "decline", policy(participation="decline_all"),
        keys, (), (), as_of=PAY, decision="decline")
    declined = post_rights_transition(account, result)
    assert declined.cash == 100 and declined.book.positions == account.book.positions
    assert audit_rights(declined.book, initial_cash=D(100)).passed


def test_rehashed_later_supported_policy_change_fails_independent_account_binding():
    account = granted_account()
    chosen = (replace(requests(account.book)[0], units=1),)
    first = post_rights_transition(account, election(account, payment=chosen))
    second = post_rights_transition(first, election(first, payment=chosen, action="second",
        stamp="2024-01-03T10:00:00+08:00"))
    assert second.cash == 80
    command = json.loads(second.book.receipts[-1].command_json)
    command["terms"]["policy"]["cutoff_boundary"] = "exclusive"
    command["terms"]["policy_id"] = fingerprint(command["terms"]["policy"])
    receipt = ActionReceipt("second", fingerprint(command), canonical(command))
    forged = replace(second.book, receipts=(*second.book.receipts[:-1], receipt))
    audit = audit_rights(forged, initial_cash=D(100))
    assert not audit.passed and any("policy changed" in issue for issue in audit.issues)
