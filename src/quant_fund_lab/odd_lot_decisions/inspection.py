"""Read-only research inspection reuses protocol/registry/report authentication."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..odd_lot_protocol.decision import policy_from_plan
from ..odd_lot_protocol.registry_read import ReadOnlyExperimentRegistry
from ..odd_lot_protocol.storage import load_protocol
from ..odd_lot_protocol.types import (
    ExperimentAttempt,
    ExperimentRecord,
    StudyProtocol,
    canonical_json,
)
from .phased_reporting import verify_phased_decision_report
from .selection_capture import SavedDevelopmentSelection, load_development_selection
from .workflow import verify_registered_decision_report


@dataclass(frozen=True)
class ResearchOverview:
    protocol: StudyProtocol
    experiments: tuple[ExperimentRecord, ...]
    histories: tuple[tuple[str, tuple[ExperimentAttempt, ...]], ...]


@dataclass(frozen=True)
class SavedDecisionView:
    directory: Path
    protocol_id: str
    schema_version: int
    decision_json: str
    selection_json: str | None
    sources_json: str


def inspect_research(protocol_directory: str | Path, *, registry_path: str | Path) -> ResearchOverview:
    """Include every declared candidate, including never-attempted and failed ones."""
    protocol = load_protocol(protocol_directory)
    policy_from_plan(protocol.analysis_plan_json)
    with ReadOnlyExperimentRegistry(registry_path) as registry:
        registry.connection.execute("BEGIN")
        if registry.get_protocol(protocol.protocol_id) != protocol:
            raise ValueError("research protocol differs from registered content")
        experiments = registry.experiments(protocol.protocol_id)
        by_candidate = {record.candidate_id:record for record in experiments}
        if (len(by_candidate) != len(experiments)
                or not set(by_candidate).issubset(row.candidate_id for row in protocol.candidates)):
            raise ValueError("research registry candidates differ from the frozen budget")
        histories = tuple((candidate.candidate_id,
            registry.attempts(by_candidate[candidate.candidate_id].experiment_id)
            if candidate.candidate_id in by_candidate else ()) for candidate in protocol.candidates)
    return ResearchOverview(protocol, experiments, histories)


def inspect_selection(protocol_directory: str | Path, selection_directory: str | Path, *,
                       registry_path: str | Path, studies_directory: str | Path) -> SavedDevelopmentSelection:
    if load_protocol(selection_directory) != load_protocol(protocol_directory):
        raise ValueError("saved selection belongs to another protocol")
    return load_development_selection(selection_directory, registry_path=registry_path,
                                       studies_directory=studies_directory)


def inspect_decision(protocol_directory: str | Path, decision_directory: str | Path, *,
                      registry_path: str | Path, studies_directory: str | Path) -> SavedDecisionView:
    """Never turn a failed verification into displayable performance evidence."""
    root = Path(decision_directory)
    protocol = load_protocol(protocol_directory)
    if load_protocol(root) != protocol:
        raise ValueError("saved decision belongs to another protocol")
    manifest = json.loads((root / "report_manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise TypeError("invalid decision manifest")
    version = manifest.get("schema_version")
    if type(version) is not int or version not in {1, 2}:
        raise ValueError("unsupported saved decision schema")
    if version == 2:
        # Surface source/profile errors from the shared capture loader before the
        # boolean report verifier, without inventing a second validation policy.
        inspect_selection(protocol_directory, root / "selection", registry_path=registry_path,
                           studies_directory=studies_directory)
        valid = verify_phased_decision_report(root, registry_path=registry_path, studies_directory=studies_directory)
    else:
        valid = verify_registered_decision_report(root, registry_path=registry_path, studies_directory=studies_directory)
    if not valid:
        raise ValueError("saved decision source reconstruction failed; use its frozen environment and inspect source integrity")
    payload = json.loads((root / "decision.json").read_text(encoding="utf-8"))
    decision = payload["decision"] if version == 2 else payload
    selection = json.loads((root / "development_selection.json").read_text(encoding="utf-8")) if version == 2 else None
    return SavedDecisionView(root, protocol.protocol_id, version, canonical_json(decision),
        canonical_json(selection) if selection is not None else None,
        (root / "sources.json").read_text(encoding="utf-8"))
