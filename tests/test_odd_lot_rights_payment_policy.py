"""Explicit elections and intraday cutoff checks precede actual cash transitions."""
# Historical duplicate retained after concurrent recovery. The complete cases
# run in test_odd_lot_rights_explicit_authorization.py, with added canonical
# receipt assertions. Keep these original functions for historical references
# and fixture imports without collecting the same 26 cases a second time.
__test__ = False

from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_odd_lot_rights_transitions import HASHES, PAY, granted, requests

from quant_fund_lab.odd_lot_rights.codec import decode_book, encode_book
from quant_fund_lab.odd_lot_rights.payment_authorization import (
    apply_authorized_subscription,
    authorize_subscription,
)
from quant_fund_lab.odd_lot_rights.session_policy import (
    PaymentInterval,
    RightsSessionPolicy,
    SubscriptionElection,
)
from quant_fund_lab.odd_lot_rights.transitions import subscribe_batch


def setup(cash="100"):
    book = granted(cash)
    batch = requests(book, fee="0.125")
    policy = RightsSessionPolicy(1, "Asia/Taipei", "2024-01-03T08:30:00+08:00",
        (SubscriptionElection("pay", batch),), "usable_cash_only_atomic", "do_not_subscribe")
    intervals = tuple(PaymentInterval(row.terms.right_key, PAY,
        "2024-01-03T14:00:00+08:00", "2024-01-03T08:00:00+08:00", HASHES) for row in batch)
    return book, batch, policy, intervals


def test_authorized_multileg_payment_preserves_exact_cash_and_replay_identity():
    book, batch, policy, intervals = setup()
    auth = authorize_subscription(policy, "pay", batch, intervals, as_of=PAY)
    result = apply_authorized_subscription(book, auth)
    assert result.book.cash == D("9.75") and result.cash_delta == D("-90.25")
    assert book.cash == 100
    assert auth.policy_sha256 == policy.policy_sha256
    restored = decode_book(encode_book(result.book))
    duplicate = apply_authorized_subscription(restored, auth, recorded=auth)
    assert not duplicate.applied and encode_book(duplicate.book) == encode_book(restored)
    with pytest.raises(ValueError, match="recorded authorization"):
        apply_authorized_subscription(restored, auth)
    changed = replace(auth, policy=replace(policy, frozen_at="2024-01-03T08:31:00+08:00"))
    assert changed.policy_sha256 != auth.policy_sha256
    with pytest.raises(ValueError, match="unchanged recorded"):
        apply_authorized_subscription(restored, changed, recorded=auth)
    with pytest.raises(ValueError, match="no matching book receipt"):
        apply_authorized_subscription(book, auth, recorded=auth)


@pytest.mark.parametrize("stamp", [PAY, "2024-01-03T14:00:00+08:00", "2024-01-03T06:00:00+00:00"])
def test_exact_interval_endpoints_and_equivalent_utc_clock_pay(stamp):
    book, batch, policy, intervals = setup()
    auth = authorize_subscription(policy, "pay", batch, intervals, as_of=stamp)
    assert apply_authorized_subscription(book, auth).book.cash == D("9.75")


@pytest.mark.parametrize("stamp", ["2024-01-03T08:59:59+08:00", "2024-01-03T14:00:01+08:00"])
def test_date_only_eligibility_cannot_override_intraday_cutoff(stamp):
    book, batch, policy, intervals = setup()
    before = encode_book(book)
    with pytest.raises(ValueError, match="outside the evidenced"):
        authorize_subscription(policy, "pay", batch, intervals, as_of=stamp)
    assert encode_book(book) == before


def test_no_election_does_not_subscribe_even_with_abundant_cash():
    book, batch, policy, intervals = setup("1000000")
    policy = replace(policy, elections=())
    before = encode_book(book)
    with pytest.raises(ValueError, match="not explicitly elected"):
        authorize_subscription(policy, "pay", batch, intervals, as_of=PAY)
    assert encode_book(book) == before


@pytest.mark.parametrize("change", ["partial", "quantity", "fee", "price", "evidence", "action"])
def test_frozen_election_binds_every_leg_quantity_fee_terms_and_action(change):
    book, batch, policy, intervals = setup()
    action = "pay"
    if change == "partial":
        batch = batch[:1]
    elif change == "quantity":
        batch = (replace(batch[0], units=4), batch[1])
    elif change == "fee":
        batch = (replace(batch[0], fee=D(0)), batch[1])
    elif change in {"price", "evidence"}:
        terms = replace(batch[0].terms, **({"unit_price": D(9)} if change == "price"
                       else {"evidence_sha256": ("c" * 64,)}))
        batch = (replace(batch[0], terms=terms), batch[1])
    else:
        action = "another"
    before = encode_book(book)
    with pytest.raises(ValueError):
        authorize_subscription(policy, action, batch, intervals, as_of=PAY)
    assert encode_book(book) == before


def test_atomic_cash_shortage_does_not_pay_only_the_affordable_leg():
    book, batch, policy, intervals = setup("90")
    before = encode_book(book)
    auth = authorize_subscription(policy, "pay", batch, intervals, as_of=PAY)
    with pytest.raises(ValueError, match="insufficient usable cash"):
        apply_authorized_subscription(book, auth)
    assert encode_book(book) == before


def test_completed_later_state_cannot_be_backdated_into_an_earlier_cutoff():
    book, batch, policy, intervals = setup()
    # A completed later close anchors the authoritative usable cash clock.
    # The fixture uses a real core receipt, not a modified `through` field.
    small = (replace(batch[0], units=1, fee=D(0)),)
    later = subscribe_batch(book, "later-close", small, as_of="2024-01-03T15:00:00+08:00").book
    before = encode_book(later)
    auth = authorize_subscription(policy, "pay", batch, intervals, as_of=PAY)
    with pytest.raises(ValueError, match="cannot precede the completed clock"):
        apply_authorized_subscription(later, auth)
    with pytest.raises(ValueError, match="outside the evidenced"):
        authorize_subscription(policy, "pay", batch, intervals, as_of="2024-01-03T15:00:00+08:00")
    assert encode_book(later) == before


@pytest.mark.parametrize("change", ["missing", "duplicate", "future", "outside_dates"])
def test_each_leg_requires_known_matching_interval_inside_payment_dates(change):
    book, batch, policy, intervals = setup()
    stamp = PAY
    if change == "missing":
        intervals = ()
    elif change == "duplicate":
        intervals = (intervals[0], intervals[0])
    elif change == "future":
        intervals = (replace(intervals[0], available_at="2024-01-03T09:00:01+08:00"), intervals[1])
    else:
        stamp = "2024-01-06T09:00:00+08:00"
        intervals = tuple(replace(row, starts_at=stamp, ends_at="2024-01-06T14:00:00+08:00")
                          for row in intervals)
    with pytest.raises(ValueError):
        authorize_subscription(policy, "pay", batch, intervals, as_of=stamp)
    assert book.cash == 100


def test_policy_cannot_freeze_future_terms_or_be_used_before_it_was_frozen():
    _, batch, policy, intervals = setup()
    with pytest.raises(ValueError, match="unavailable when"):
        replace(policy, frozen_at="2024-01-03T07:59:59+08:00")
    future = replace(policy, frozen_at="2024-01-03T09:01:00+08:00")
    with pytest.raises(ValueError, match="not frozen"):
        authorize_subscription(future, "pay", batch, intervals, as_of=PAY)


@pytest.mark.parametrize("changes", [
    {"schema_version": True}, {"timezone": "UTC"}, {"cash_rule": "borrow_future_cash"},
    {"unlisted_action": "subscribe_if_affordable"}, {"elections": []},
])
def test_policy_rejects_unsupported_or_mutable_contracts(changes):
    _, _, policy, _ = setup()
    with pytest.raises((TypeError, ValueError)):
        replace(policy, **changes)


def test_election_order_duplicates_and_overnight_interval_are_not_ambiguous():
    _, batch, policy, intervals = setup()
    for invalid in (tuple(reversed(batch)), (batch[0], batch[0])):
        with pytest.raises(ValueError, match="unique and canonically ordered"):
            SubscriptionElection("pay", invalid)
    with pytest.raises(ValueError, match="actions must be unique"):
        replace(policy, elections=(policy.elections[0], policy.elections[0]))
    with pytest.raises(ValueError, match="one ordered Taipei"):
        replace(intervals[0], ends_at="2024-01-04T14:00:00+08:00")
