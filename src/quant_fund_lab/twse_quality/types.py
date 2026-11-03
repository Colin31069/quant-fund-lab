"""Immutable public contracts for evidence-backed study readiness."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from enum import Enum

READINESS_RULE_VERSION = "readiness-v2"


class FindingCode(str, Enum):
    MISSING_MONTH = "missing_month"
    MISSING_SESSION = "missing_session"
    SOURCE_INTEGRITY = "source_integrity"
    SOURCE_CONFLICT = "source_conflict"
    COVERAGE_REVIEW = "coverage_review"
    UNSUPPORTED_EVENT = "unsupported_event"
    EVENT_CONFLICT = "event_conflict"
    DERIVED_STATE = "invalid_derived_state"
    CALENDAR = "calendar"
    WARMUP = "warmup"
    MISSING_SYMBOL = "missing_symbol"
    UNKNOWN = "unknown"


class ReadinessStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


def fingerprint(value: object) -> str:
    """Hash canonical JSON, rejecting non-finite numbers and unsupported objects."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _interval(start: str, end: str) -> None:
    if date.fromisoformat(start).isoformat() != start:
        raise ValueError("dates must use canonical ISO format")
    if date.fromisoformat(end).isoformat() != end or end < start:
        raise ValueError("date interval must be canonical and ordered")


@dataclass(frozen=True)
class ReadinessFinding:
    """Semantic identity excludes translated display text and source file locations."""

    code: FindingCode
    symbol: str
    start: str
    end: str
    detail: str
    discriminator: str = ""
    source_refs: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    policy_id: str = "twse_official"
    occurrences: int = 1
    blocking: bool = True
    applicability_reason: str = ""

    def __post_init__(self) -> None:
        _interval(self.start, self.end)
        if not isinstance(self.code, FindingCode) or not self.symbol or not self.policy_id:
            raise ValueError("finding requires a typed code, symbol and source policy")
        if type(self.occurrences) is not int or self.occurrences < 1:
            raise ValueError("finding occurrences must be a positive integer")
        if type(self.blocking) is not bool or (not self.blocking and not self.applicability_reason):
            raise ValueError("nonblocking context requires an explicit applicability reason")

    @property
    def finding_id(self) -> str:
        return fingerprint([self.policy_id, self.code.value, self.symbol,
                            self.start, self.end, self.discriminator])

    def to_dict(self) -> dict:
        return {"finding_id": self.finding_id, **asdict(self)}


@dataclass(frozen=True)
class WarmupEvidence:
    """Verified sessions include only complete observations or sourced suspensions."""

    calendar_revision: str
    required: int
    expected_sessions: tuple[str, ...]
    verified_sessions: tuple[str, ...]
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.required) is not int or self.required < 1 or not self.calendar_revision:
            raise ValueError("warmup requires a positive count and calendar revision")
        for sessions in (self.expected_sessions, self.verified_sessions):
            if tuple(sorted(set(sessions))) != sessions:
                raise ValueError("warmup sessions must be unique and ordered")
            for day in sessions:
                _interval(day, day)
        if not set(self.verified_sessions).issubset(self.expected_sessions):
            raise ValueError("verified warmup sessions must belong to expected sessions")

    @property
    def complete(self) -> bool:
        return (len(self.expected_sessions) >= self.required
                and self.expected_sessions == self.verified_sessions)


@dataclass(frozen=True)
class PeriodReadiness:
    period: str
    start: str
    end: str
    status: ReadinessStatus
    warmup: WarmupEvidence
    blocking_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _interval(self.start, self.end)
        if not self.period or not isinstance(self.status, ReadinessStatus):
            raise ValueError("period requires a name and typed status")
        if self.status == ReadinessStatus.READY and (self.blocking_ids or not self.warmup.complete):
            raise ValueError("ready period cannot have blockers or incomplete warmup")


@dataclass(frozen=True)
class StudyReadiness:
    input_fingerprint: str
    findings: tuple[ReadinessFinding, ...]
    periods: tuple[PeriodReadiness, ...]
    limitations: tuple[str, ...] = ()
    schema_version: int = 1
    rule_version: str = READINESS_RULE_VERSION

    def __post_init__(self) -> None:
        if (type(self.schema_version) is not int or self.schema_version != 1
                or not self.rule_version or not self.input_fingerprint):
            raise ValueError("readiness requires supported schema and versioned inputs")
        ids = [finding.finding_id for finding in self.findings]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate semantic findings")
        references = {key for p in self.periods for key in p.blocking_ids}
        references.update(key for f in self.findings for key in f.depends_on)
        if not references.issubset(ids):
            raise ValueError("readiness references an unknown finding")
        names = [p.period for p in self.periods]
        if len(set(names)) != len(names):
            raise ValueError("duplicate readiness periods")

    def to_dict(self) -> dict:
        result = asdict(self)
        result["findings"] = [f.to_dict() for f in self.findings]
        return result

    @property
    def readiness_fingerprint(self) -> str:
        """Bind the full serialized decision and its evidence to a reproducible result."""
        return fingerprint(self.to_dict())
