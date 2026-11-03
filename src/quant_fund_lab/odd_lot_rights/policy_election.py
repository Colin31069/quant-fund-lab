"""Post explicit policy-bound elections without implicit funding or leg priority."""
import json
from dataclasses import asdict
from decimal import localcontext
from zoneinfo import ZoneInfo

from .payment_policy import PaymentCutoff, RightsParticipationPolicy
from .transitions import ZERO, _begin, _finish, _position, subscribe_batch
from .types import PaymentRequest, RightsBook, RightsTransition, clock


def elect_subscription(
    book: RightsBook,
    action_id: str,
    policy: RightsParticipationPolicy,
    right_keys: tuple[str, ...],
    requests: tuple[PaymentRequest, ...],
    cutoffs: tuple[PaymentCutoff, ...],
    *,
    as_of: str,
    decision: str,
) -> RightsTransition:
    """Record the full policy, exact election and daily cutoff in one receipt.

    Declining records a decision without expiring unpaid rights or consuming
    paid claims. An explicit payment uses only current spendable cash; the
    original full-batch cash check remains authoritative. These local records
    do not prove historical source truth or prior protocol registration.
    """
    if not isinstance(policy, RightsParticipationPolicy):
        raise TypeError("election requires a typed participation policy")
    if (type(right_keys) is not tuple or not right_keys
            or any(not isinstance(key, str) or not key for key in right_keys)
            or len(set(right_keys)) != len(right_keys)
            or type(requests) is not tuple or any(not isinstance(row, PaymentRequest) for row in requests)
            or type(cutoffs) is not tuple or any(not isinstance(row, PaymentCutoff) for row in cutoffs)):
        raise TypeError("election requires explicit unique rights and immutable typed requests/cutoffs")
    if decision not in {"pay", "decline"}:
        raise ValueError("election requires an explicit pay or decline decision")
    terms = {"available_at": policy.frozen_at, "policy": asdict(policy), "policy_id": policy.policy_id,
             "decision": decision,
             "right_keys": right_keys, "requests": [asdict(row) for row in requests],
             "cutoffs": [asdict(row) for row in cutoffs]}
    started = _begin(book, action_id, as_of, {"kind": "policy_election", "terms": terms})
    if started is None:
        return RightsTransition(book, action_id, ZERO, applied=False)
    identity, today = started
    for receipt in book.receipts:
        previous = json.loads(receipt.command_json)
        if (previous["kind"] == "policy_election"
                and previous["terms"]["policy_id"] != policy.policy_id):
            raise ValueError("election policy differs from the account's frozen policy")
    stamp = clock(as_of)
    if clock(policy.frozen_at) > stamp:
        raise ValueError("election policy was not yet available")
    for key in right_keys:
        row = _position(book, key)
        if row.leg.kind != "subscription" or row.unpaid <= 0:
            raise ValueError("election scope requires outstanding subscription rights")
    if policy.participation == "decline_all" and decision != "decline":
        raise ValueError("decline policy cannot authorize a payment decision")
    if decision == "decline":
        if requests or cutoffs:
            raise ValueError("decline policy cannot contain payment requests or cutoff elections")
        return _finish(book, action_id, as_of, identity, book.positions, book.cash)
    requested = [row.terms.right_key for row in requests]
    windows = {row.right_key: row for row in cutoffs}
    if (not requests or len(set(requested)) != len(requested) or set(requested) != set(right_keys)
            or len(windows) != len(cutoffs) or set(windows) != set(right_keys)):
        raise ValueError("explicit election requires exactly one request and cutoff for each scoped leg")
    for request in requests:
        window = windows[request.terms.right_key]
        opening, cutoff = clock(window.opens_at), clock(window.cutoff_at)
        payment_day = opening.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat()
        if clock(window.available_at) > stamp:
            raise ValueError("payment cutoff evidence was not yet available")
        if (today != payment_day or stamp < opening or stamp > cutoff
                or (stamp == cutoff and policy.cutoff_boundary == "exclusive")):
            raise ValueError("payment processing is outside the evidenced daily cutoff")
    # Reuse the established pure cash/quantity calculation, discarding its local
    # temporary receipt. Only the full policy_election command is published.
    calculated = subscribe_batch(book, action_id, requests, as_of=as_of)
    with localcontext() as context:
        context.prec = 80
        return _finish(book, action_id, as_of, identity, calculated.book.positions, calculated.book.cash)
