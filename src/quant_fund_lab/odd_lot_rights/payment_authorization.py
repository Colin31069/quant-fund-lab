"""Authorize a frozen atomic election before the existing cash transition runs."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from zoneinfo import ZoneInfo

from .codec import fingerprint
from .payment_policy import PaymentCutoff, RightsParticipationPolicy
from .policy_election import elect_subscription
from .session_policy import PaymentInterval, RightsSessionPolicy
from .transitions import subscribe_batch
from .types import PaymentRequest, RightsBook, RightsTransition, clock


@dataclass(frozen=True)
class PaymentAuthorization:
    """Revalidated input for orchestration, with policy and command identities.

    The outer workflow must persist this authorization with the resulting book
    atomically. The old rights-book codec does not store or enforce this policy.
    No source-authentication or durable-integration claim is made by this type.

    The current application adapter additionally records the canonical
    policy_election receipt. Its policy name binds this full frozen policy's
    SHA; requests and intervals are stored in that receipt. The old-codec
    limitation above refers to legacy bare subscribe receipts, which remain
    replayable only with their separately authenticated original authorization.
    """

    policy: RightsSessionPolicy
    action_id: str
    requests: tuple[PaymentRequest, ...]
    intervals: tuple[PaymentInterval, ...]
    as_of: str

    def __post_init__(self) -> None:
        if not isinstance(self.policy, RightsSessionPolicy):
            raise TypeError("authorization requires a typed frozen policy")
        now = clock(self.as_of)
        if clock(self.policy.frozen_at) > now:
            raise ValueError("policy was not frozen at the processing clock")
        election = next((row for row in self.policy.elections
                         if row.action_id == self.action_id), None)
        if election is None:
            raise ValueError("action was not explicitly elected; automatic subscription is forbidden")
        if self.requests != election.requests or type(self.requests) is not tuple:
            raise ValueError("payment batch differs from the complete frozen election")
        if (type(self.intervals) is not tuple
                or any(not isinstance(row, PaymentInterval) for row in self.intervals)):
            raise TypeError("authorization requires immutable typed payment intervals")
        keys = tuple(row.right_key for row in self.intervals)
        expected = tuple(row.terms.right_key for row in self.requests)
        if keys != expected:
            raise ValueError("each elected leg requires exactly one ordered payment interval")
        zone = ZoneInfo(self.policy.timezone)
        today = now.astimezone(zone).date().isoformat()
        for request, interval in zip(self.requests, self.intervals):
            terms = request.terms
            if clock(interval.available_at) > now:
                raise ValueError("payment interval was not available at the processing clock")
            if not clock(interval.starts_at) <= now <= clock(interval.ends_at):
                raise ValueError("processing clock is outside the evidenced payment interval")
            if not terms.payment_start <= today <= terms.payment_end:
                raise ValueError("payment interval is outside the elected terms' payment dates")

    @property
    def authorization_sha256(self) -> str:
        return fingerprint(asdict(self))

    @property
    def policy_sha256(self) -> str:
        return self.policy.policy_sha256


def authorize_subscription(policy: RightsSessionPolicy, action_id: str,
                           requests: tuple[PaymentRequest, ...],
                           intervals: tuple[PaymentInterval, ...], *,
                           as_of: str) -> PaymentAuthorization:
    """Reject missing elections/times before any caller invokes subscribe_batch.

    Cash priority is a full-batch check in subscribe_batch, using the book at this
    exact clock. It never borrows later T+2 receipts or silently drops a leg.
    """
    return PaymentAuthorization(policy, action_id, requests, intervals, as_of)


def apply_authorized_subscription(book: RightsBook, authorization: PaymentAuthorization,
                                 *, recorded: PaymentAuthorization | None = None) -> RightsTransition:
    """Apply the authorized batch; require the original authorization on retry.

    The outer workflow authenticates `recorded` against its archived original,
    and atomically saves new authorizations with book/inventory changes. Without
    that archive, an old core receipt alone cannot establish its policy binding.

    New payments use the shared policy_election record, never a second cash
    path. The full instruction policy SHA is part of the canonical policy name,
    so changing a later election cannot silently change the account policy.
    """
    if not isinstance(authorization, PaymentAuthorization):
        raise TypeError("payment requires a typed authorization")
    receipt = next((row for row in book.receipts if row.action_id == authorization.action_id), None)
    if receipt is not None:
        if (not isinstance(recorded, PaymentAuthorization)
                or recorded.authorization_sha256 != authorization.authorization_sha256):
            raise ValueError("payment replay requires its unchanged recorded authorization")
    elif recorded is not None:
        raise ValueError("recorded payment authorization has no matching book receipt")
    if receipt is not None and json.loads(receipt.command_json)["kind"] == "subscribe":
        # Preserve verified replay of the earlier explicit-authorization API;
        # never rewrite its original receipt into a new command kind.
        return subscribe_batch(book, authorization.action_id, authorization.requests,
                               as_of=authorization.as_of)
    policy = RightsParticipationPolicy(
        "authorization:"+authorization.policy_sha256, authorization.policy.frozen_at,
        "explicit_election", "reject_batch", "retain_until_evidenced",
        "explicit_current_marks", "already_usable", "inclusive")
    cutoffs = tuple(PaymentCutoff(row.right_key, row.starts_at, row.ends_at,
                                 row.available_at, row.evidence_sha256)
                    for row in authorization.intervals)
    return elect_subscription(book, authorization.action_id, policy,
        tuple(row.terms.right_key for row in authorization.requests), authorization.requests,
        cutoffs, as_of=authorization.as_of, decision="pay")
