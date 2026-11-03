"""Explicit authorization now shares canonical policy receipts and replay guards."""
from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_odd_lot_rights_explicit_authorization import setup
from test_odd_lot_rights_transitions import PAY

from quant_fund_lab.odd_lot_rights.audit import audit_rights
from quant_fund_lab.odd_lot_rights.codec import decode_book, encode_book
from quant_fund_lab.odd_lot_rights.payment_authorization import (
    apply_authorized_subscription,
    authorize_subscription,
)
from quant_fund_lab.odd_lot_rights.session_policy import SubscriptionElection
from quant_fund_lab.odd_lot_rights.transitions import subscribe_batch


def two_elections():
    book, batch, policy, intervals = setup()
    first = (replace(batch[0], units=1, fee=D(0)),)
    second = (replace(batch[1], units=1, fee=D(0)),)
    policy = replace(policy, elections=(SubscriptionElection("pay-a", first),
                                       SubscriptionElection("pay-b", second)))
    return book, policy, first, second, intervals


def test_multiple_predeclared_actions_share_one_policy_and_audited_cash_after_restart():
    book, policy, first, second, intervals = two_elections()
    auth = authorize_subscription(policy, "pay-a", first, intervals[:1], as_of=PAY)
    result = apply_authorized_subscription(book, auth)
    assert result.book.cash == 90
    restored = decode_book(encode_book(result.book))
    later = authorize_subscription(policy, "pay-b", second, intervals[1:],
                                    as_of="2024-01-03T09:01:00+08:00")
    final = apply_authorized_subscription(restored, later).book
    assert final.cash == 70 and sum(row.pending for row in final.positions) == 12
    assert audit_rights(final, initial_cash=D(100)).passed
    assert decode_book(encode_book(final)) == final


def test_changing_a_later_instruction_cannot_change_policy_after_first_payment():
    book, policy, first, second, intervals = two_elections()
    first_auth = authorize_subscription(policy, "pay-a", first, intervals[:1], as_of=PAY)
    paid = apply_authorized_subscription(book, first_auth).book
    changed_request = (replace(second[0], fee=D(1)),)
    changed = replace(policy, elections=(policy.elections[0], SubscriptionElection("pay-b", changed_request)))
    new_auth = authorize_subscription(changed, "pay-b", changed_request, intervals[1:],
                                       as_of="2024-01-03T09:01:00+08:00")
    before = encode_book(paid)
    with pytest.raises(ValueError, match="account's frozen policy"):
        apply_authorized_subscription(paid, new_auth)
    assert encode_book(paid) == before


def test_canonical_receipt_rejects_changed_interval_even_if_caller_relabels_recorded_auth():
    book, batch, policy, intervals = setup()
    auth = authorize_subscription(policy, "pay", batch, intervals, as_of=PAY)
    paid = apply_authorized_subscription(book, auth).book
    changed = replace(auth, intervals=(replace(intervals[0], available_at="2024-01-03T08:01:00+08:00"), intervals[1]))
    before = encode_book(paid)
    with pytest.raises(ValueError, match="completed rights action payload changed"):
        apply_authorized_subscription(paid, changed, recorded=changed)
    assert encode_book(paid) == before


def test_legacy_bare_subscribe_receipt_replays_without_rewriting_its_kind_or_bytes():
    book, batch, policy, intervals = setup()
    auth = authorize_subscription(policy, "pay", batch, intervals, as_of=PAY)
    legacy = subscribe_batch(book, "pay", batch, as_of=PAY).book
    encoded = encode_book(legacy)
    replay = apply_authorized_subscription(decode_book(encoded), auth, recorded=auth)
    assert not replay.applied and encode_book(replay.book) == encoded


def test_zero_length_payment_interval_is_not_a_bank_acceptance_window():
    _, _, _, intervals = setup()
    with pytest.raises(ValueError, match="one ordered Taipei"):
        replace(intervals[0], ends_at=intervals[0].starts_at)
