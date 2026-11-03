"""Typed results of source-backed forward-session assessment, before account writes."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime

from ..twse_odd_lot import TWSEInput
from ..twse_quality.types import StudyReadiness
from .ledger import canonical, digest


@dataclass(frozen=True)
class SessionEvidence:
    plan_id: str
    first_session: str
    through_session: str
    checked_at: str
    calendar_revision: str
    readiness_fingerprint: str
    source_hashes: tuple[tuple[str, str], ...]
    # (session, symbol, source_id, retrieved_at); source_id binds path/URL/raw hash.
    acquisitions: tuple[tuple[str, str, str, str], ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (type(self.source_hashes) is not tuple or type(self.acquisitions) is not tuple
                or any(type(row) is not tuple for row in (*self.source_hashes, *self.acquisitions))):
            raise ValueError("session evidence requires immutable tuple records")
        for value in (self.plan_id, self.readiness_fingerprint,
                      *(value for _, value in self.source_hashes)):
            if not re.fullmatch(r"[a-f0-9]{64}", value):
                raise ValueError("session evidence requires complete source identities")
        if (date.fromisoformat(self.first_session).isoformat() != self.first_session
                or date.fromisoformat(self.through_session).isoformat() != self.through_session
                or self.first_session > self.through_session):
            raise ValueError("session evidence requires canonical ordered dates")
        if (not self.calendar_revision or not self.source_hashes or not self.acquisitions
                or type(self.schema_version) is not int or self.schema_version != 1):
            raise ValueError("session evidence requires calendar, sources and acquisitions")
        if tuple(sorted(self.source_hashes)) != self.source_hashes or len(dict(self.source_hashes)) != len(self.source_hashes):
            raise ValueError("session evidence source inventory must be unique and sorted")
        checked = datetime.fromisoformat(self.checked_at)
        if checked.tzinfo is None or checked.utcoffset() is None:
            raise ValueError("session assessment requires explicit timezone")
        keys = set()
        for session, symbol, source_id, recorded in self.acquisitions:
            stamp = datetime.fromisoformat(recorded.replace("Z", "+00:00"))
            if (not self.first_session <= session <= self.through_session
                    or date.fromisoformat(session).isoformat() != session
                    or not re.fullmatch(r"\d{4,6}\.TW", symbol)
                    or not re.fullmatch(r"[a-f0-9]{64}", source_id)
                    or stamp.tzinfo is None or stamp.utcoffset() is None or stamp > checked
                    or (session, symbol) in keys):
                raise ValueError("invalid or duplicate session acquisition evidence")
            keys.add((session, symbol))

    @property
    def evidence_id(self) -> str:
        return digest(canonical(asdict(self)))


@dataclass(frozen=True)
class ForwardSessionAssessment:
    status: str
    reasons: tuple[str, ...]
    inputs: TWSEInput
    readiness: StudyReadiness
    evidence: SessionEvidence | None

    def __post_init__(self) -> None:
        if (self.status not in {"ready", "blocked"}
                or (self.status == "ready") != (self.evidence is not None)
                or (self.status == "ready") == bool(self.reasons)):
            raise ValueError("forward assessment status must match evidence and reasons")
        if self.evidence is not None and (
                self.evidence.readiness_fingerprint != self.readiness.readiness_fingerprint
                or dict(self.evidence.source_hashes) != self.inputs.source_hashes):
            raise ValueError("forward assessment evidence differs from reconstructed sources")
