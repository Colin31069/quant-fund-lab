"""Capture complete registry prefixes and reconstruct development without validation accounts."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from ..odd_lot_protocol.build import verify_candidate_binding
from ..odd_lot_protocol.decision import decision_budgets, policy_from_plan
from ..odd_lot_protocol.registry_read import ReadOnlyExperimentRegistry
from ..odd_lot_protocol.storage import load_protocol
from ..odd_lot_protocol.types import StudyProtocol, canonical_json
from ..odd_lot_study import load_frozen_odd_lot_study
from .development import DevelopmentSelection
from .development_report import (
    dependency_fingerprint,
    report_development_evidence,
    report_inventory,
)
from .development_source_types import DevelopmentInputs
from .development_types import DevelopmentEvidence, DevelopmentPolicy
from .registry_evidence import _prefix_matches
from .source_types import DecisionSource
from .types import STRATEGIES, fingerprint


def _observe(protocol: StudyProtocol, registry_path: Path, studies: Path, loaded: dict,
             snapshot: tuple[DecisionSource, ...] | None) -> tuple[DecisionSource, ...]:
    if not registry_path.is_file() or registry_path.is_symlink():
        raise ValueError("development requires an existing experiment registry")
    if snapshot is not None and (not isinstance(snapshot, tuple)
                                or not all(isinstance(row, DecisionSource) for row in snapshot)):
        raise ValueError("development snapshot requires typed immutable sources")
    saved = {row.candidate_id: row for row in snapshot} if snapshot is not None else {}
    if snapshot is not None and (not isinstance(snapshot, tuple) or len(saved) != len(snapshot)
                                or set(saved) != {row.candidate_id for row in protocol.candidates}):
        raise ValueError("development snapshot must cover the complete candidate budget")
    with ReadOnlyExperimentRegistry(registry_path) as registry:
        registry.connection.execute("BEGIN")
        if registry.get_protocol(protocol.protocol_id) != protocol:
            raise ValueError("development protocol differs from registered content")
        experiments = registry.experiments(protocol.protocol_id)
        records = {row.candidate_id: row for row in experiments}
        if len(records) != len(experiments) or not set(records).issubset(row.candidate_id for row in protocol.candidates):
            raise ValueError("development registry contains foreign or duplicate candidates")
        histories = {key: registry.attempts(row.experiment_id) for key, row in records.items()}
    result = []
    for candidate in protocol.candidates:
        record, source = records.get(candidate.candidate_id), saved.get(candidate.candidate_id)
        attempts = histories.get(candidate.candidate_id, ())
        if source is not None:
            if source.experiment is None:
                record, attempts = None, ()
            else:
                if record != source.experiment or not _prefix_matches(source.attempts, attempts):
                    raise ValueError("development snapshot differs from registered history prefix")
                attempts = source.attempts
        if record is not None and (record.study_id != candidate.study_id
                or record.execution_id != protocol.execution.identity):
            raise ValueError("development experiment differs from frozen candidate")
        manifests = {}
        for attempt in attempts:
            if attempt.report_path is not None:
                manifest = report_inventory(Path(attempt.report_path), studies, protocol, record, attempt,
                                            loaded[candidate.candidate_id][1])
                manifests[str(attempt.attempt)] = manifest["report_id"]
        observed = DecisionSource(candidate.candidate_id,
            canonical_json(asdict(record)) if record is not None else None,
            canonical_json([asdict(row) for row in attempts]), canonical_json(manifests))
        if source is not None and source != observed:
            raise ValueError("development report inventory differs from captured sources")
        result.append(observed)
    return tuple(result)


def _load(protocol: StudyProtocol, studies: Path) -> dict:
    result = {}
    for candidate in protocol.candidates:
        directory = studies / candidate.study_id
        if directory.is_symlink() or (directory / "study.json").is_symlink():
            raise ValueError("development frozen study cannot be a symlink")
        for folder in (directory / "sources", directory / "snapshot"):
            if folder.is_symlink() or any(path.is_symlink() for path in folder.rglob("*")):
                raise ValueError("development frozen source inventory cannot contain symlinks")
        data, metadata = load_frozen_odd_lot_study(directory)
        verify_candidate_binding(protocol, candidate, metadata)
        result[candidate.candidate_id] = (data, metadata)
    return result


def collect_registered_development(protocol_directory: str | Path, *, registry_path: str | Path,
                                    studies_directory: str | Path,
                                    snapshot: tuple[DecisionSource, ...] | None = None) -> DevelopmentInputs:
    """Read-only development analysis; not a persisted or validated final decision.

    Frozen market inputs/readiness are authenticated in full. Other-period report
    payloads are hashed as opaque bytes, never parsed as performance evidence.
    The explicit source_rule identifies this analysis; legacy v5 workflow remains
    unchanged until a new phased protocol/workflow is separately frozen.
    """
    protocol_root, registry, studies = Path(protocol_directory), Path(registry_path), Path(studies_directory)
    protocol = load_protocol(protocol_root)
    decision_budgets(protocol)
    policy = policy_from_plan(protocol.analysis_plan_json)
    development = next(period for period in protocol.periods if period.name == "development")
    ranking_policy = DevelopmentPolicy.from_decision_policy(policy, start=development.start, end=development.end)
    loaded = _load(protocol, studies)
    sources = _observe(protocol, registry, studies, loaded, snapshot)
    evidence = []
    for source in sources:
        data, metadata = loaded[source.candidate_id]
        latest = source.attempts[-1] if source.attempts else None
        status, reason = "unavailable", "candidate not registered or never attempted"
        if any(row.reason.startswith("nonreproducible numerical result") for row in source.attempts):
            status, reason = "failed", "unresolved nonreproducible numerical result in captured history"
        elif latest is not None:
            if latest.status == "running":
                reason = "latest registered attempt is still running"
            elif latest.report_path is None or latest.reason.startswith("nonreproducible numerical result"):
                status = "blocked" if latest.status == "blocked" else "failed"
                reason = latest.reason or "latest attempt has no verified development report"
            else:
                report = Path(latest.report_path)
                inventory = report_inventory(report, studies, protocol, source.experiment, latest, metadata)
                evidence.extend(report_development_evidence(report, data, metadata, protocol, set(inventory["files"])))
                continue
        proof = fingerprint({"development": dependency_fingerprint(data, metadata, protocol),
                             "availability": status, "reason": reason})
        evidence.extend(DevelopmentEvidence(source.candidate_id, strategy, status, proof, reason) for strategy in STRATEGIES)
    selection = DevelopmentSelection(ranking_policy, tuple(row.candidate_id for row in protocol.candidates), tuple(evidence))
    # Reconstruct source inputs again so races in normalized snapshots or their raw
    # lineage cannot hide behind an unchanged report inventory or registry prefix.
    current = _load(protocol, studies)
    if load_protocol(protocol_root) != protocol or _observe(protocol, registry, studies, current, snapshot) != sources:
        raise ValueError("development source history or protocol changed during collection")
    return DevelopmentInputs(sources, selection)
