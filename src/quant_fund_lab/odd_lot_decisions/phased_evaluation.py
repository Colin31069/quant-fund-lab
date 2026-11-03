"""Read validation only through a reconstructed, already persisted development capture."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..odd_lot_protocol.decision import decision_budgets, policy_from_plan
from ..odd_lot_protocol.decision_rules import PHASED_ENGINE
from ..odd_lot_protocol.storage import load_protocol
from ..odd_lot_protocol.types import json_object
from .report_evidence import checked_report, report_candidate_evidence
from .selected_evaluation import evaluate_selected_development
from .selection_capture import SavedDevelopmentSelection, load_development_selection
from .types import CandidateEvidence, ResearchDecision


@dataclass(frozen=True)
class PhasedEvaluation:
    saved: SavedDevelopmentSelection
    decision: ResearchDecision
    validation: CandidateEvidence | None


def evaluate_saved_selection(directory: str | Path, *, registry_path: str | Path,
                              studies_directory: str | Path) -> PhasedEvaluation:
    """Replay the saved prefix, not necessarily the registry's latest observation.

    This path neither creates a selection nor runs a candidate experiment. A live
    publisher must additionally reject captures that no longer match current sources.
    """
    protocol = load_protocol(directory)
    if json_object(protocol.analysis_plan_json).get("engine") != PHASED_ENGINE:
        raise ValueError("saved-selection validation requires an explicit phased protocol")
    policy = policy_from_plan(protocol.analysis_plan_json)
    # This must finish before any full report verifier or validation parser runs.
    saved = load_development_selection(directory, registry_path=registry_path, studies_directory=studies_directory)
    selection = saved.inputs.selection
    evidence = None
    if selection.selected_candidate is not None:
        source = next(row for row in saved.inputs.sources if row.candidate_id == selection.selected_candidate)
        record, attempt = source.experiment, source.attempts[-1]
        report = Path(attempt.report_path)
        checked_report(report, Path(studies_directory), protocol, record, attempt)
        matched = json.loads((report / "matched_sensitivity.json").read_text(encoding="utf-8"))
        unavailable = json.loads((report / "unavailable.json").read_text(encoding="utf-8"))
        expected = "failed" if matched["status"] == "failed" else "blocked" if (
            matched["status"] == "blocked" or unavailable) else "succeeded"
        if attempt.status != expected:
            raise ValueError("saved validation attempt status differs from report outcomes")
        evidence, = report_candidate_evidence(report, Path(studies_directory), protocol, record, attempt,
                                               strategies=(selection.selected_strategy,))
    decision = evaluate_selected_development(protocol.protocol_id, policy, decision_budgets(protocol), selection, evidence)
    after = load_development_selection(directory, registry_path=registry_path, studies_directory=studies_directory)
    if after != saved or load_protocol(directory) != protocol:
        raise ValueError("saved selection or sources changed during validation")
    return PhasedEvaluation(saved, decision, evidence)
