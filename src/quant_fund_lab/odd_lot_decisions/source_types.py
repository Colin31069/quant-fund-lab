"""Immutable registry-prefix references for reproducible, locally verifiable decisions."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from ..odd_lot_protocol.types import ExperimentAttempt, ExperimentRecord, canonical_json, digest
from .types import CandidateEvidence


@dataclass(frozen=True)
class DecisionSource:
    candidate_id: str
    experiment_json: str | None
    history_json: str
    report_manifests_json: str

    def __post_init__(self) -> None:
        digest(self.candidate_id)
        history = json.loads(self.history_json)
        manifests = json.loads(self.report_manifests_json)
        if (not isinstance(history, list) or not isinstance(manifests, dict)
                or canonical_json(history) != self.history_json
                or canonical_json(manifests) != self.report_manifests_json):
            raise ValueError("decision sources require canonical history and report identities")
        record = self.experiment
        if record is None:
            if history or manifests:
                raise ValueError("unregistered candidate cannot claim attempt or report evidence")
            return
        if canonical_json(asdict(record)) != self.experiment_json or record.candidate_id != self.candidate_id:
            raise ValueError("decision source experiment differs from candidate")
        attempts = self.attempts
        for number, attempt in enumerate(attempts, 1):
            if (attempt.attempt != number or attempt.experiment_id != record.experiment_id
                    or attempt.status == "running" and number != len(attempts)):
                raise ValueError("decision source history is not an ordered attempt prefix")
        expected = {str(row.attempt) for row in attempts if row.report_path is not None}
        if set(manifests) != expected:
            raise ValueError("decision source report inventory differs from attempt history")
        for value in manifests.values():
            digest(value)

    @property
    def experiment(self) -> ExperimentRecord | None:
        return ExperimentRecord(**json.loads(self.experiment_json)) if self.experiment_json is not None else None

    @property
    def attempts(self) -> tuple[ExperimentAttempt, ...]:
        return tuple(ExperimentAttempt(**values) for values in json.loads(self.history_json))

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DecisionInputs:
    sources: tuple[DecisionSource, ...]
    evidence: tuple[CandidateEvidence, ...]

    def to_dict(self) -> dict:
        return {"sources": [row.to_dict() for row in self.sources],
                "evidence": [asdict(row) for row in self.evidence]}
