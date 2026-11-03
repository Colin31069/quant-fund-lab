"""Typed, provider-preserving raw-price and source-selection contracts."""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from ..twse_quality.types import fingerprint


def iso_day(value: str) -> str:
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("price dates must use canonical ISO format")
    return value


@dataclass(frozen=True)
class PriceSourcePolicy:
    start: str
    end: str
    cutoff: str
    priority: tuple[str, ...] = ("TWSE", "FinMind")
    policy_id: str = "reviewed_provider_v1"
    price_atol: float = 1e-8
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not iso_day(self.start) <= iso_day(self.end) <= iso_day(self.cutoff):
            raise ValueError("invalid price policy range or cutoff")
        if (type(self.schema_version) is not int
                or (self.schema_version, self.policy_id) not in {
                    (1, "reviewed_provider_v1"), (2, "reviewed_provider_v2")}
                or self.price_atol != 1e-8):
            raise ValueError("unsupported price policy or precision rule")
        if (not self.priority or len(set(self.priority)) != len(self.priority)
                or not set(self.priority).issubset({"TWSE", "FinMind"})):
            raise ValueError("price priority must contain unique known providers")

    @property
    def policy_fingerprint(self) -> str:
        return fingerprint(asdict(self))

    @property
    def accepts_reviewed_symbol_halts(self) -> bool:
        """V2 accepts no quote only with independently loaded individual halt evidence.

        This computed rule adds no serialized fields, preserving old v1 policy
        bytes and fingerprints. No-quote rows alone never attest to a halt.
        """
        return self.schema_version == 2


@dataclass(frozen=True)
class PriceSourceRef:
    provider: str
    dataset: str
    source_url: str
    retrieved_at: str
    raw_path: str
    sha256: str
    usage: str
    authorization_basis: tuple[str, ...]
    price_basis: str = "raw_unadjusted"
    volume_unit: str = "shares"
    converter_revision: str = "raw-price-v1"

    def __post_init__(self) -> None:
        expected = {"FinMind": "TaiwanStockPrice", "TWSE": "STOCK_DAY"}
        if expected.get(self.provider) != self.dataset:
            raise ValueError("provider and raw dataset identity differ")
        url = urlparse(self.source_url)
        host = (url.hostname or "").lower()
        allowed = (host == "api.finmindtrade.com" if self.provider == "FinMind" else
                   host == "twse.com.tw" or host.endswith(".twse.com.tw"))
        if url.scheme != "https" or not allowed:
            raise ValueError("price source URL differs from provider identity")
        if (datetime.fromisoformat(self.retrieved_at.replace("Z", "+00:00")).tzinfo is None
                or not re.fullmatch(r"[a-f0-9]{64}", self.sha256)):
            raise ValueError("source requires timezone-aware retrieval and SHA-256")
        path = Path(self.raw_path)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise ValueError("raw source path must remain inside the bundle")
        if (self.price_basis != "raw_unadjusted" or self.volume_unit != "shares"
                or not self.usage or not self.authorization_basis or not self.converter_revision):
            raise ValueError("source requires explicit raw basis, units and usage evidence")

    @property
    def source_id(self) -> str:
        return fingerprint(asdict(self))


@dataclass(frozen=True)
class PriceObservation:
    symbol: str
    date: str
    raw_open: float | None
    raw_high: float | None
    raw_low: float | None
    raw_close: float | None
    volume_shares: int
    no_quote: bool
    source: PriceSourceRef
    row_locator: str
    turnover_twd: int | None = None
    trades: int | None = None

    def __post_init__(self) -> None:
        iso_day(self.date)
        if not re.fullmatch(r"\d{4,6}\.TW", self.symbol) or not self.row_locator:
            raise ValueError("observation requires listed symbol and raw row locator")
        if type(self.volume_shares) is not int or self.volume_shares < 0 or type(self.no_quote) is not bool:
            raise ValueError("volume must be a nonnegative share count; quote flag must be boolean")
        prices = (self.raw_open, self.raw_high, self.raw_low, self.raw_close)
        if any(value is not None and (type(value) is not int or value < 0)
               for value in (self.turnover_twd, self.trades)):
            raise ValueError("turnover and trade counts must be nonnegative integers")
        if self.no_quote:
            if any(value is not None for value in prices):
                raise ValueError("no-quote prices must be explicitly absent, never executable zeros")
        else:
            if any(value is None or isinstance(value, bool) or not math.isfinite(value) or value <= 0
                   for value in (self.raw_open, self.raw_close)):
                raise ValueError("quoted open/close must be positive finite prices")
            if (self.raw_high is None) != (self.raw_low is None):
                raise ValueError("high and low must be supplied together")
            if self.raw_high is not None and (not math.isfinite(self.raw_high)
                    or not math.isfinite(self.raw_low)
                    or not 0 < self.raw_low <= min(self.raw_open, self.raw_close)
                    <= max(self.raw_open, self.raw_close) <= self.raw_high):
                raise ValueError("invalid OHLC envelope")


@dataclass(frozen=True)
class PriceBundle:
    sources: tuple[PriceSourceRef, ...]
    observations: tuple[PriceObservation, ...]
    manifest_sha256: str
    cutoff: str
    source_files: tuple[tuple[str, Path], ...]

    def __post_init__(self) -> None:
        iso_day(self.cutoff)
        ids = {s.source_id for s in self.sources}
        if len(ids) != len(self.sources) or not re.fullmatch(r"[a-f0-9]{64}", self.manifest_sha256):
            raise ValueError("bundle requires unique source references and manifest hash")
        if any(row.source.source_id not in ids or row.date > self.cutoff for row in self.observations):
            raise ValueError("bundle observation differs from source inventory or cutoff")

    @property
    def bundle_fingerprint(self) -> str:
        return fingerprint({"sources": [s.source_id for s in self.sources],
                            "manifest_sha256": self.manifest_sha256, "cutoff": self.cutoff,
                            "observations": [observation_identity(r) for r in self.observations]})


@dataclass(frozen=True)
class PriceConflict:
    symbol: str
    date: str
    source_ids: tuple[str, ...]
    fields: tuple[str, ...]


@dataclass(frozen=True)
class PriceSelection:
    policy: PriceSourcePolicy
    selected: tuple[PriceObservation, ...]
    conflicts: tuple[PriceConflict, ...]
    candidate_source_ids: tuple[str, ...]

    @property
    def selection_fingerprint(self) -> str:
        return fingerprint({"policy": self.policy.policy_fingerprint,
                            "selected": [observation_identity(r) for r in self.selected],
                            "conflicts": [asdict(c) for c in self.conflicts],
                            "candidate_source_ids": self.candidate_source_ids})


def observation_identity(row: PriceObservation) -> tuple:
    """Bind values as well as lineage, including in-memory transformations."""
    return (row.symbol, row.date, row.raw_open, row.raw_high, row.raw_low, row.raw_close,
            row.volume_shares, row.no_quote, row.turnover_twd, row.trades,
            row.source.source_id, row.row_locator)
