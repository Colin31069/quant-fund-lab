"""Read complete attempt prefixes and authenticate report evidence before any ranking."""
from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

from ..odd_lot_protocol.decision import decision_budgets
from ..odd_lot_protocol.decision_rules import PHASED_ENGINE
from ..odd_lot_protocol.registry_read import ReadOnlyExperimentRegistry
from ..odd_lot_protocol.storage import load_protocol
from ..odd_lot_protocol.types import ExperimentAttempt, canonical_json, json_object
from .report_evidence import checked_report, report_candidate_evidence
from .source_types import DecisionInputs, DecisionSource
from .types import STRATEGIES, CandidateEvidence, PeriodEvidence, fingerprint


def _prefix_matches(captured: tuple[ExperimentAttempt, ...], current: tuple[ExperimentAttempt, ...]) -> bool:
    if len(captured) > len(current):
        return False
    for before, now in zip(captured, current):
        if before.status == "running":
            now = replace(now, status="running", finished_at=None, result_fingerprint=None, report_path=None, reason="")
        if before != now:
            return False
    return True


def _unavailable(candidate_id: str, status: str, reason: str, proof: str) -> tuple[CandidateEvidence, ...]:
    period = PeriodEvidence(status, reason)
    return tuple(CandidateEvidence(candidate_id, strategy, period, period, period, (), proof) for strategy in STRATEGIES)


def collect_decision_inputs(protocol_directory: str | Path, *, registry_path: str | Path,
                             studies_directory: str | Path,
                             snapshot: tuple[DecisionSource, ...] | None = None) -> DecisionInputs:
    """Default to the latest full history; explicit snapshots replay recorded prefixes.

    A saved incomplete snapshot stays incomplete after later work. Terminal rows
    must still match; a captured running row may since have reached completion.
    Prefix replay proves stored lifecycle/content, not independently signed timing
    or that a saved snapshot still represents the latest registry state.
    """
    protocol = load_protocol(protocol_directory)
    if json_object(protocol.analysis_plan_json).get("engine") == PHASED_ENGINE:
        raise ValueError("phased decisions require a saved development selection")
    decision_budgets(protocol)
    registry_root, studies = Path(registry_path), Path(studies_directory)
    if not registry_root.is_file() or registry_root.is_symlink():
        raise ValueError("decision sources require an existing experiment registry")
    if snapshot is not None and (not isinstance(snapshot, tuple)
            or {row.candidate_id for row in snapshot} != {row.candidate_id for row in protocol.candidates}
            or len(snapshot) != len(protocol.candidates)):
        raise ValueError("decision source snapshot must cover the exact finite candidate set")
    saved = {row.candidate_id: row for row in snapshot} if snapshot is not None else {}
    with ReadOnlyExperimentRegistry(registry_root) as registry:
        registry.connection.execute("BEGIN")
        if registry.get_protocol(protocol.protocol_id) != protocol:
            raise ValueError("decision protocol differs from registered content")
        records = {row.candidate_id: row for row in registry.experiments(protocol.protocol_id)}
        histories = {key: registry.attempts(row.experiment_id) for key, row in records.items()}
    sources, evidence = [], []
    for candidate in protocol.candidates:
        candidate_id = candidate.candidate_id
        record = records.get(candidate_id)
        source = saved.get(candidate_id)
        if snapshot is None:
            attempts = histories.get(candidate_id, ())
        elif source.experiment is None:
            # Absence is only an incomplete captured observation, never positive evidence.
            record, attempts = None, ()
        else:
            if record != source.experiment or not _prefix_matches(source.attempts, histories.get(candidate_id, ())):
                raise ValueError("captured decision history differs from registry prefix")
            attempts = source.attempts
        manifests = {}
        if record is not None:
            for attempt in attempts:
                if attempt.report_path is not None:
                    manifests[str(attempt.attempt)] = checked_report(Path(attempt.report_path), studies, protocol, record, attempt)
        observed = DecisionSource(candidate_id, canonical_json(asdict(record)) if record is not None else None,
            canonical_json([asdict(row) for row in attempts]), canonical_json(manifests))
        if source is not None and source != observed:
            raise ValueError("captured report identity differs from the registered source")
        sources.append(observed)
        latest = attempts[-1] if attempts else None
        proof = fingerprint([protocol.protocol_id, candidate_id, record.experiment_id if record else None,
                             latest.result_fingerprint if latest else None, latest.status if latest else "missing"])
        if record is None or latest is None:
            evidence.extend(_unavailable(candidate_id, "unavailable", "candidate not registered or never attempted", proof))
        elif latest.status == "running":
            evidence.extend(_unavailable(candidate_id, "unavailable", "latest registered attempt is still running", proof))
        elif latest.report_path is None or latest.reason.startswith("nonreproducible numerical result"):
            status = "blocked" if latest.status == "blocked" else "failed"
            evidence.extend(_unavailable(candidate_id, status, latest.reason or "latest attempt has no verified report", proof))
        else:
            report = Path(latest.report_path)
            matched = json.loads((report / "matched_sensitivity.json").read_text(encoding="utf-8"))
            unavailable = json.loads((report / "unavailable.json").read_text(encoding="utf-8"))
            expected = "failed" if matched["status"] == "failed" else "blocked" if (
                matched["status"] == "blocked" or unavailable) else "succeeded"
            if latest.status != expected:
                raise ValueError("registered attempt status differs from verified report outcomes")
            evidence.extend(report_candidate_evidence(report, studies, protocol, record, latest))
    return DecisionInputs(tuple(sources), tuple(evidence))
