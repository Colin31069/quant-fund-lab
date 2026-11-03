"""Rank development evidence once, then inspect validation without fallback selection."""
from __future__ import annotations

from dataclasses import asdict, replace

from .types import (
    STRATEGIES,
    CandidateBudget,
    CandidateDecision,
    CandidateEvidence,
    DecisionCheck,
    DecisionPolicy,
    PeriodEvidence,
    ResearchDecision,
    _digest,
    fingerprint,
)
from .validation import validation_checks


def _development(policy: DecisionPolicy, evidence: PeriodEvidence) -> tuple[str, float | None, str]:
    if evidence.status != "available":
        return "unavailable", None, "development_" + evidence.status + ": " + evidence.reason
    if evidence.completed_episodes is None:
        return "unavailable", None, "development_episode_count_unknown"
    if evidence.completed_episodes < policy.minimum_completed_trades:
        return "insufficient_sample", None, "development_completed_episodes_below_minimum"
    score = getattr(evidence, policy.development_objective)
    if score is None:
        return "unavailable", None, "development_objective_undefined"
    if policy.development_objective == "calmar" and (evidence.max_drawdown is None or evidence.max_drawdown == 0):
        return "unavailable", None, "calmar_undefined_without_drawdown"
    if policy.development_objective == "sharpe" and (evidence.annual_volatility is None or evidence.annual_volatility <= 0):
        return "unavailable", None, "sharpe_undefined_without_variation"
    return "eligible", float(score), "development_eligible"

def evaluate_research_decision(protocol_id: str, policy: DecisionPolicy,
                               budgets: tuple[CandidateBudget, ...],
                               evidence: tuple[CandidateEvidence, ...]) -> ResearchDecision:
    """Pure core. Report/registry authentication and protocol-policy binding belong to adapters."""
    _digest(protocol_id)
    if not isinstance(budgets, tuple) or not budgets or not isinstance(evidence, tuple):
        raise ValueError("decision evaluation requires finite immutable input tuples")
    by_id = {row.candidate_id: row for row in budgets}
    by_key = {(row.candidate_id, row.strategy): row for row in evidence}
    if len(by_id) != len(budgets) or len(by_key) != len(evidence):
        raise ValueError("duplicate candidate budget or evidence")
    if any(row.candidate_id not in by_id for row in evidence):
        raise ValueError("evidence belongs to an undeclared candidate")
    if any(not {item.scenario_id for item in row.sensitivity}.issubset(by_id[row.candidate_id].scenario_ids) for row in evidence):
        raise ValueError("evidence belongs to an undeclared sensitivity scenario")
    rows = []
    for candidate_id in sorted(by_id):
        for strategy in STRATEGIES:
            item = by_key.get((candidate_id, strategy))
            status, score, reason = (_development(policy, item.development) if item else
                                      ("unavailable", None, "declared_candidate_evidence_missing"))
            rows.append(CandidateDecision(candidate_id, strategy, status, score, (reason,),
                (DecisionCheck("development/objective", "passed" if status == "eligible" else status,
                               score, None, reason),)))
    fingerprint_inputs = [{**asdict(row), "sensitivity": sorted(
        [asdict(item) for item in row.sensitivity], key=lambda value: value["scenario_id"])}
        for row in sorted(evidence, key=lambda value: (value.candidate_id, value.strategy))]
    proof = fingerprint({"budgets": [asdict(row) for row in sorted(budgets, key=lambda value: value.candidate_id)],
                         "evidence": fingerprint_inputs})
    eligible = [row for row in rows if row.status == "eligible"]
    status, selected, reasons = "incomplete_search", None, ("development_evidence_incomplete",)
    if not any(row.status == "unavailable" for row in rows):
        if not eligible:
            status, reasons = "insufficient_sample", ("no_candidate_meets_development_sample_minimum",)
        else:
            selected = min(eligible, key=lambda row: (-row.development_score, row.candidate_id, row.strategy))
            status, reasons, checks = validation_checks(policy, by_key[(selected.candidate_id, selected.strategy)], by_id[selected.candidate_id])
            rows = [replace(row, status=status, reasons=reasons, checks=row.checks + checks) if row == selected else
                    replace(row, status="not_selected", reasons=("lower_development_rank_no_validation_fallback",))
                    if row.status == "eligible" else row for row in rows]
    return ResearchDecision(protocol_id, policy, status, selected.candidate_id if selected else None,
                            selected.strategy if selected else None, tuple(rows), proof, reasons)
