"""Frozen, explicit payment elections and evidenced intraday payment intervals."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from zoneinfo import ZoneInfo

from .codec import fingerprint
from .types import PaymentRequest, clock, evidence


@dataclass(frozen=True)
class SubscriptionElection:
    """An entire atomic batch chosen explicitly, including terms and exact fees."""

    action_id: str
    requests: tuple[PaymentRequest, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, str) or not self.action_id:
            raise ValueError("election requires an explicit action identity")
        if (type(self.requests) is not tuple or not self.requests
                or any(not isinstance(row, PaymentRequest) for row in self.requests)):
            raise TypeError("election requires an immutable typed payment batch")
        keys = tuple(row.terms.right_key for row in self.requests)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("election legs must be unique and canonically ordered")


@dataclass(frozen=True)
class RightsSessionPolicy:
    """Version-one manual elections; no cash-based participation or fallback.

    Unlisted actions are declined. All selected legs are paid together from the
    authoritative usable cash, or none are paid. This first policy deliberately
    supports the same Taipei session clock as the existing rights engine.
    """

    schema_version: int
    timezone: str
    frozen_at: str
    elections: tuple[SubscriptionElection, ...]
    cash_rule: str
    unlisted_action: str

    def __post_init__(self) -> None:
        frozen = clock(self.frozen_at)
        if (type(self.schema_version) is not int or self.schema_version != 1
                or self.timezone != "Asia/Taipei"
                or self.cash_rule != "usable_cash_only_atomic"
                or self.unlisted_action != "do_not_subscribe"):
            raise ValueError("unsupported rights session policy semantics")
        if (type(self.elections) is not tuple
                or any(not isinstance(row, SubscriptionElection) for row in self.elections)):
            raise TypeError("policy requires immutable typed elections")
        actions = tuple(row.action_id for row in self.elections)
        if actions != tuple(sorted(set(actions))):
            raise ValueError("policy actions must be unique and canonically ordered")
        if any(clock(request.terms.available_at) > frozen
               for row in self.elections for request in row.requests):
            raise ValueError("election cannot use terms unavailable when the policy was frozen")

    @property
    def policy_sha256(self) -> str:
        return fingerprint(asdict(self))


@dataclass(frozen=True)
class PaymentInterval:
    """One evidenced same-day acceptance interval, inclusive at both endpoints.

    A date-only payment window is insufficient. The source adapter must establish
    the actual acceptance interval and authenticate these evidence references.
    Intervals do not assert bank availability or authenticate their own source.
    """

    right_key: str
    starts_at: str
    ends_at: str
    available_at: str
    evidence_sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        start, end = clock(self.starts_at), clock(self.ends_at)
        evidence(self.available_at, self.evidence_sha256)
        zone = ZoneInfo("Asia/Taipei")
        if (not isinstance(self.right_key, str) or not self.right_key or end <= start
                or start.astimezone(zone).date() != end.astimezone(zone).date()):
            raise ValueError("payment interval requires one ordered Taipei calendar day")
