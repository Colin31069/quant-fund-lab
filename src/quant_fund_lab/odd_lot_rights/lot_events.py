"""Explicit opening corporate-action contracts and conservative lot rounding."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..odd_lot_paper.sale_limits import OpeningSaleLimits
from .inventory import SecurityLot
from .types import day, evidence, number


@dataclass(frozen=True)
class OpeningLotEvent:
    """A source adapter supplies known split/terminal facts for this opening.

    Cash dividends and fractional proceeds remain owned by the existing engine;
    this contract only transforms whole-share ownership and release restrictions.
    Receipt exchanges use their separate explicit conversion contract.
    """

    event_id: str
    security_id: str
    session: str
    kind: str
    ratio: Decimal | None
    available_at: str
    evidence_sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        day(self.session)
        evidence(self.available_at, self.evidence_sha256)
        evidence(self.available_at, (self.event_id,))
        if not isinstance(self.security_id, str) or not self.security_id:
            raise ValueError("lot event requires a stable security identity")
        if self.kind == "split":
            number(self.ratio)
            if self.ratio <= 0 or self.ratio == 1:
                raise ValueError("split event requires an explicit positive non-unit ratio")
        elif self.kind != "terminal" or self.ratio is not None:
            raise ValueError("lot event requires supported split or terminal semantics")


@dataclass(frozen=True)
class LotRoundingPolicy:
    """Pool residual whole units with the latest contributor's release date.

    This explicit conservative engineering policy may delay execution. It does
    not establish an issuer's pooling rules, fees or fractional cash proceeds.
    """

    schema_version: int
    residual_rule: str

    def __post_init__(self) -> None:
        if (type(self.schema_version) is not int or self.schema_version != 1
                or self.residual_rule != "latest_contributor_release"):
            raise ValueError("unsupported lot rounding policy")


@dataclass(frozen=True)
class SplitLotFraction:
    event_id: str
    right_key: str
    security_id: str
    fraction: Decimal
    tradable_session: str


@dataclass(frozen=True)
class OpeningLotProjection:
    """Pre-execution plan, never an already-posted RightsInventory checkpoint.

    source_sha256 binds the account, events, policy and processing clock. The
    orchestrator must verify event terms against actual engine actions and save
    the corporate movements with fills atomically in its versioned checkpoint.
    """

    source_sha256: str
    lots: tuple[SecurityLot, ...]
    fractions: tuple[SplitLotFraction, ...]
    shares: tuple[tuple[str, int], ...]
    fractional_units: tuple[tuple[str, Decimal], ...]
    sale_limits: OpeningSaleLimits
