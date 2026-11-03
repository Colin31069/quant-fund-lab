"""Explicit participation and evidenced daily payment-window contracts."""
from dataclasses import asdict, dataclass
from zoneinfo import ZoneInfo

from .codec import fingerprint
from .types import clock, evidence


@dataclass(frozen=True)
class RightsParticipationPolicy:
    """Content-addressed election semantics, to be bound to a registered protocol.

    frozen_at is a declared knowledge boundary, not authenticated publication or
    registration time. The outer workflow must authenticate its prior freezing.
    Every behavior is explicit; unsupported fallback/valuation choices fail.
    """

    name: str
    frozen_at: str
    participation: str
    insufficient_funds: str
    fractional_rights: str
    valuation: str
    cash_source: str
    cutoff_boundary: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        clock(self.frozen_at)
        if (not isinstance(self.name, str) or not self.name
                or self.participation not in {"explicit_election", "decline_all"}
                or self.insufficient_funds != "reject_batch"
                or self.fractional_rights != "retain_until_evidenced"
                or self.valuation != "explicit_current_marks"
                or self.cash_source != "already_usable"
                or self.cutoff_boundary not in {"inclusive", "exclusive"}
                or type(self.schema_version) is not int or self.schema_version != 1):
            raise ValueError("rights participation policy requires explicit supported behavior")

    @property
    def policy_id(self) -> str:
        return fingerprint(asdict(self))


@dataclass(frozen=True)
class PaymentCutoff:
    """One evidenced daily payable interval; date-only terms are insufficient.

    The same-day open/cutoff must be disclosed and authenticated by the source
    adapter. A closed bank day must not be represented as a payable interval.
    Boundary inclusivity is an explicit frozen policy choice.
    """

    right_key: str
    opens_at: str
    cutoff_at: str
    available_at: str
    evidence_sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        evidence(self.available_at, self.evidence_sha256)
        opening, cutoff = clock(self.opens_at), clock(self.cutoff_at)
        zone = ZoneInfo("Asia/Taipei")
        if (not self.right_key or opening >= cutoff
                or opening.astimezone(zone).date() != cutoff.astimezone(zone).date()):
            raise ValueError("payment cutoff requires one ordered daily interval and a rights leg")
