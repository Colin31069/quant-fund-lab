"""Immutable, versioned contracts for finite odd-lot research experiments."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime

from ..twse_quality.types import fingerprint


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def json_object(value: str) -> dict:
    parsed = json.loads(value)
    if not isinstance(parsed, dict) or canonical_json(parsed) != value:
        raise ValueError("protocol JSON must be a canonical finite object")
    return parsed


def digest(value: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("protocol identity requires a full SHA-256")


def iso_date(value: str) -> None:
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("protocol dates must use canonical ISO format")


@dataclass(frozen=True)
class ExecutionIdentity:
    revision: str
    code_diff_sha256: str
    source_tree_sha256: str
    environment_json: str

    def __post_init__(self) -> None:
        if not self.revision:
            raise ValueError("execution identity requires a code revision")
        digest(self.code_diff_sha256)
        digest(self.source_tree_sha256)
        json_object(self.environment_json)

    @property
    def identity(self) -> str:
        return fingerprint(asdict(self))


@dataclass(frozen=True)
class ProtocolPeriod:
    name: str
    start: str
    end: str
    purpose: str
    data_access: str
    access_note: str

    def __post_init__(self) -> None:
        iso_date(self.start)
        iso_date(self.end)
        if not self.name or self.start > self.end or not self.access_note.strip():
            raise ValueError("protocol period requires ordered dates and a data-access note")
        if self.purpose not in {"development_selection", "validation_check",
                                "historical_exploration", "forward_observation"}:
            raise ValueError("unknown research period purpose")
        if self.data_access not in {"accessed", "unknown", "unseen"}:
            raise ValueError("unknown data-access status")
        if self.purpose == "forward_observation" and self.data_access != "unseen":
            raise ValueError("accessed or unknown data cannot be labeled unseen forward observation")
        if self.data_access == "unseen" and self.purpose != "forward_observation":
            raise ValueError("only a prospective forward period can declare unseen data")
        if (self.end >= "2025-01-01" and self.data_access != "unseen"
                and self.purpose != "historical_exploration"):
            raise ValueError("accessed or unknown post-2025 data must remain exploratory")


@dataclass(frozen=True)
class ProtocolCandidate:
    study_id: str
    research_json: str
    backtest_json: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{24}", self.study_id):
            raise ValueError("candidate requires a frozen study ID")
        json_object(self.research_json)
        json_object(self.backtest_json)

    @property
    def candidate_id(self) -> str:
        return fingerprint([json_object(self.research_json), json_object(self.backtest_json)])


@dataclass(frozen=True)
class SelectionRule:
    development_objective: str
    validation_rule: str
    rejection_rule: str
    minimum_completed_trades: int = 30
    tie_break: str = "candidate_id_ascending"

    def __post_init__(self) -> None:
        if self.development_objective not in {"calmar", "sharpe", "annual_return"}:
            raise ValueError("unsupported development objective")
        if (not self.validation_rule.strip() or not self.rejection_rule.strip()
                or type(self.minimum_completed_trades) is not int
                or self.minimum_completed_trades < 30 or self.tie_break != "candidate_id_ascending"):
            raise ValueError("selection requires explicit rules and at least 30 completed trades")


@dataclass(frozen=True)
class StudyProtocol:
    dataset_id: str
    input_fingerprint: str
    source_policy_json: str
    calendar_revisions: tuple[str, ...]
    symbols: tuple[str, ...]
    benchmark: str
    warmup: int
    periods: tuple[ProtocolPeriod, ...]
    candidates: tuple[ProtocolCandidate, ...]
    max_candidates: int
    selection: SelectionRule
    analysis_plan_json: str
    execution: ExecutionIdentity
    declared_at: str
    seed: int = 0
    parent_protocol_id: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        for value in (self.dataset_id, self.input_fingerprint):
            digest(value)
        json_object(self.source_policy_json)
        json_object(self.analysis_plan_json)
        stamp = datetime.fromisoformat(self.declared_at)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("protocol declaration requires an explicit timezone")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported protocol schema")
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("protocol seed must be a nonnegative integer")
        for values in (self.symbols, self.periods, self.candidates, self.calendar_revisions):
            if not isinstance(values, tuple) or not values:
                raise ValueError("protocol collections must be nonempty immutable tuples")
        if (len(self.symbols) < 2 or len(set(self.symbols)) != len(self.symbols)
                or self.benchmark in self.symbols or not self.benchmark):
            raise ValueError("protocol needs distinct trade assets and a separate benchmark")
        if (type(self.warmup) is not int or self.warmup < 120
                or type(self.max_candidates) is not int or self.max_candidates != len(self.candidates)):
            raise ValueError("protocol requires full warmup and an exact finite candidate budget")
        ids = [c.candidate_id for c in self.candidates]
        if len(set(ids)) != len(ids) or len({p.name for p in self.periods}) != len(self.periods):
            raise ValueError("duplicate protocol candidates or periods")
        ordered = sorted(self.periods, key=lambda p: p.start)
        if any(a.end >= b.start for a, b in zip(ordered, ordered[1:])):
            raise ValueError("protocol periods cannot overlap")
        for period in self.periods:
            if period.data_access == "unseen" and period.start <= str(stamp.date()):
                raise ValueError("historical data cannot become an unseen forward period")
        if self.parent_protocol_id is not None:
            digest(self.parent_protocol_id)

    @property
    def protocol_id(self) -> str:
        return fingerprint(asdict(self))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict) -> StudyProtocol:
        payload = dict(values)
        payload["periods"] = tuple(ProtocolPeriod(**v) for v in payload["periods"])
        payload["candidates"] = tuple(ProtocolCandidate(**v) for v in payload["candidates"])
        payload["selection"] = SelectionRule(**payload["selection"])
        payload["execution"] = ExecutionIdentity(**payload["execution"])
        for field in ("symbols", "calendar_revisions"):
            payload[field] = tuple(payload[field])
        return cls(**payload)


@dataclass(frozen=True)
class ExperimentRecord:
    experiment_id: str
    protocol_id: str
    candidate_id: str
    study_id: str
    execution_id: str

    def __post_init__(self) -> None:
        for value in (self.experiment_id, self.protocol_id, self.candidate_id, self.execution_id):
            digest(value)
        expected = fingerprint([self.protocol_id, self.candidate_id, self.study_id, self.execution_id])
        if expected != self.experiment_id:
            raise ValueError("experiment identity differs from its registered inputs")


@dataclass(frozen=True)
class ExperimentAttempt:
    experiment_id: str
    attempt: int
    status: str
    started_at: str
    finished_at: str | None = None
    result_fingerprint: str | None = None
    report_path: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        digest(self.experiment_id)
        if type(self.attempt) is not int or self.attempt < 1:
            raise ValueError("experiment attempt must be a positive integer")
        if self.status not in {"running", "succeeded", "blocked", "failed"}:
            raise ValueError("invalid experiment attempt status")
        started = datetime.fromisoformat(self.started_at)
        if started.tzinfo is None or started.utcoffset() is None:
            raise ValueError("attempt timestamp requires a timezone")
        if self.status == "running":
            if self.finished_at or self.result_fingerprint or self.report_path or self.reason:
                raise ValueError("running attempt cannot contain a terminal outcome")
        else:
            if not self.finished_at:
                raise ValueError("terminal attempt requires completion time")
            finished = datetime.fromisoformat(self.finished_at)
            if finished.tzinfo is None or finished < started:
                raise ValueError("invalid attempt completion time")
            if self.status == "succeeded" and (not self.result_fingerprint or not self.report_path):
                raise ValueError("successful attempt requires result and report")
            if self.status != "succeeded" and not self.reason.strip():
                raise ValueError("failed or blocked attempt requires a reason")
        if self.result_fingerprint is not None:
            digest(self.result_fingerprint)
