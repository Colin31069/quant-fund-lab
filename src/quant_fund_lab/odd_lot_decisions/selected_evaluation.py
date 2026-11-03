"""Apply validation to the already chosen development winner without ranking again."""
from __future__ import annotations

from dataclasses import asdict, replace

from .development import DevelopmentSelection
from .development_types import DevelopmentPolicy
from .types import (
    CandidateBudget,
    CandidateDecision,
    CandidateEvidence,
    DecisionCheck,
    DecisionPolicy,
    ResearchDecision,
    _digest,
    fingerprint,
)
from .validation import validation_checks


def evaluate_selected_development(protocol_id: str, policy: DecisionPolicy,
                                   budgets: tuple[CandidateBudget, ...], selection: DevelopmentSelection,
                                   evidence: CandidateEvidence | None) -> ResearchDecision:
    """Pure evaluator; the persisted source/capture contract belongs to the workflow."""
    _digest(protocol_id)
    if not isinstance(selection, DevelopmentSelection) or not isinstance(policy, DecisionPolicy):
        raise TypeError("fixed evaluation requires typed selection and policy")
    if not isinstance(budgets, tuple) or not all(isinstance(row, CandidateBudget) for row in budgets):
        raise TypeError("fixed evaluation requires immutable typed budgets")
    by_id = {row.candidate_id: row for row in budgets}
    if len(by_id) != len(budgets) or set(by_id) != set(selection.candidate_ids):
        raise ValueError("fixed evaluation budget differs from development selection")
    projected = DevelopmentPolicy.from_decision_policy(policy,
        start=selection.policy.development_start, end=selection.policy.development_end)
    if projected != selection.policy:
        raise ValueError("fixed evaluation policy differs from development ranking")
    selected = (selection.selected_candidate, selection.selected_strategy)
    if selection.selected_candidate is None:
        if evidence is not None:
            raise ValueError("validation evidence cannot be supplied without a development choice")
        status = selection.status
        reasons = (("development_evidence_incomplete",) if status == "incomplete_search"
                   else ("no_candidate_meets_development_sample_minimum",))
        checks = ()
    else:
        if not isinstance(evidence, CandidateEvidence) or (evidence.candidate_id, evidence.strategy) != selected:
            raise ValueError("validation evidence differs from the saved development choice")
        if not {row.scenario_id for row in evidence.sensitivity}.issubset(by_id[selected[0]].scenario_ids):
            raise ValueError("validation evidence contains undeclared scenarios")
        development = next(row for row in selection.evidence if (row.candidate_id, row.strategy) == selected)
        expected = asdict(development)
        for name in ("candidate_id", "strategy", "source_fingerprint"):
            expected.pop(name)
        if any(getattr(evidence.development, name) != value for name, value in expected.items()):
            raise ValueError("validation source development differs from saved selection")
        status, reasons, checks = validation_checks(policy, evidence, by_id[selected[0]])
    candidates = []
    for row in selection.candidates:
        initial = DecisionCheck("development/objective", "passed" if row.status == "eligible" else row.status,
                                row.score, None, row.reason)
        decision = CandidateDecision(row.candidate_id, row.strategy, row.status, row.score, (row.reason,), (initial,))
        if (row.candidate_id, row.strategy) == selected:
            decision = replace(decision, status=status, reasons=reasons, checks=decision.checks + checks)
        elif selection.selected_candidate is not None and row.status == "eligible":
            decision = replace(decision, status="not_selected", reasons=("lower_development_rank_no_validation_fallback",))
        candidates.append(decision)
    proof = fingerprint({"rule": "fixed_saved_development_v1", "selection_id": selection.selection_id,
                         "budgets": [asdict(row) for row in sorted(budgets, key=lambda row: row.candidate_id)],
                         "validation": asdict(evidence) if evidence is not None else None})
    return ResearchDecision(protocol_id, policy, status, selection.selected_candidate, selection.selected_strategy,
                            tuple(candidates), proof, reasons)
