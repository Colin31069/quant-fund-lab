"""Evaluate every predeclared validation gate, retaining failures alongside missing evidence."""
from __future__ import annotations

from .types import CandidateBudget, CandidateEvidence, DecisionCheck, DecisionPolicy, PeriodEvidence


def _sample(policy: DecisionPolicy, evidence: PeriodEvidence, context: str) -> DecisionCheck:
    if evidence.status != "available" or evidence.completed_episodes is None:
        return DecisionCheck(context + "/sample", "unavailable", None, policy.minimum_completed_trades,
                             context + "_sample_unavailable: " + evidence.status + "; " + evidence.reason)
    passed = evidence.completed_episodes >= policy.minimum_completed_trades
    return DecisionCheck(context + "/sample", "passed" if passed else "insufficient_sample",
                         evidence.completed_episodes, policy.minimum_completed_trades,
                         context + ("_sample_sufficient" if passed else "_completed_episodes_below_minimum"))


def _bound(evidence: PeriodEvidence, name: str, bound: float, context: str, *, minimum: bool) -> DecisionCheck:
    value = getattr(evidence, name)
    if evidence.status != "available" or value is None:
        return DecisionCheck(context + "/" + name, "unavailable", None, bound, context + "_" + name + "_unavailable")
    observed = -value if name == "max_drawdown" else value
    passed = observed >= bound if minimum else observed <= bound
    return DecisionCheck(context + "/" + name, "passed" if passed else "failed", observed, bound,
                         context + "_" + name + ("_within_bound" if passed else "_outside_bound"))


def validation_checks(policy: DecisionPolicy, evidence: CandidateEvidence,
                       budget: CandidateBudget) -> tuple[str, tuple[str, ...], tuple[DecisionCheck, ...]]:
    validation = evidence.validation
    checks = [_sample(policy, validation, "validation"),
              _bound(validation, "annual_return", policy.minimum_validation_annual_return, "validation", minimum=True),
              _bound(validation, "max_drawdown", policy.maximum_validation_drawdown, "validation", minimum=False)]
    if policy.require_benchmark_outperformance:
        benchmark = evidence.validation_benchmark
        if (benchmark.status != "available" or validation.status != "available"
                or benchmark.total_return is None or validation.total_return is None):
            checks.append(DecisionCheck("validation/benchmark", "unavailable", None, None, "same_cost_validation_benchmark_unavailable"))
        else:
            passed = validation.total_return > benchmark.total_return
            checks.append(DecisionCheck("validation/benchmark", "passed" if passed else "failed",
                validation.total_return, benchmark.total_return,
                "same_cost_validation_benchmark_outperformed" if passed else "same_cost_validation_benchmark_not_outperformed"))
    observed = {row.scenario_id: row.result for row in evidence.sensitivity}
    for scenario_id in budget.scenario_ids:
        scenario = observed.get(scenario_id)
        if scenario is None:
            checks.append(DecisionCheck("scenario/" + scenario_id, "unavailable", None, None,
                                        "required_sensitivity_scenario_missing/" + scenario_id))
            continue
        context = "scenario/" + scenario_id
        checks.extend((_sample(policy, scenario, context),
            _bound(scenario, "total_return", policy.minimum_sensitivity_total_return, context, minimum=True),
            _bound(scenario, "max_drawdown", policy.maximum_sensitivity_drawdown, context, minimum=False)))
    risk_required = policy.maximum_loss_to_budget_ratio is not None or policy.maximum_stop_delay_sessions is not None
    if risk_required:
        pending = validation.pending_stop_episodes
        if validation.status != "available" or pending is None:
            risk_status, reason = "unavailable", "pending_stop_count_unknown"
        elif pending:
            risk_status, reason = "insufficient_sample", "stop_exit_observation_pending"
        elif not validation.risk_evidence_complete:
            risk_status, reason = "unavailable", "validation_risk_evidence_incomplete"
        else:
            risk_status, reason = "passed", "validation_risk_evidence_complete"
        checks.append(DecisionCheck("validation/risk_evidence", risk_status, pending, 0, reason))
        for name, bound in (("maximum_loss_to_budget_ratio", policy.maximum_loss_to_budget_ratio),
                            ("maximum_stop_delay_sessions", policy.maximum_stop_delay_sessions)):
            if bound is None:
                continue
            if risk_status != "passed":
                checks.append(DecisionCheck("validation/" + name, risk_status, None, bound, reason + "/" + name))
            else:
                checks.append(_bound(validation, name, bound, "validation", minimum=False))
    priority = next((state for state in ("unavailable", "insufficient_sample", "failed")
                     if any(row.status == state for row in checks)), "passed")
    status = {"passed": "continue", "failed": "return"}.get(priority, priority)
    reasons = tuple(row.reason for row in checks if row.status != "passed") or ("all_frozen_validation_rules_satisfied",)
    return status, reasons, tuple(checks)
