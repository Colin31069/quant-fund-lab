"""Executable decision declarations remain absent from legacy protocol identities."""
from __future__ import annotations

from dataclasses import asdict

from ..odd_lot_decisions.types import CandidateBudget, DecisionPolicy
from .decision_rules import CAPTURE_RULE, PHASED_ENGINE, PHASED_SOURCE_RULE, SELECTION_RULE
from .sensitivity import declared_scenarios
from .types import ProtocolPeriod, SelectionRule, StudyProtocol, json_object


def policy_from_plan(plan_json: str) -> DecisionPolicy | None:
    plan = json_object(plan_json)
    if plan.get("engine") in {f"frozen_odd_lot_batch_v{version}" for version in range(1, 5)}:
        if (any(key in plan for key in ("decision_policy", "decision_capture_rule", "decision_selection_rule"))
                or plan.get("automatic_candidate_selection") is not False):
            raise ValueError("legacy protocol cannot declare executable selection")
        return None
    phased = plan.get("engine") == PHASED_ENGINE
    if plan.get("engine") not in {"frozen_odd_lot_batch_v5", PHASED_ENGINE} or plan.get("automatic_candidate_selection") is not True:
        raise ValueError("unsupported decision protocol plan")
    required = {"decision_ranking_period": "development",
                "decision_validation_period": "validation",
                "decision_strategies": ["ensemble", "momentum"],
                "decision_source_rule": PHASED_SOURCE_RULE if phased else "latest_registered_attempt_prefix_v1"}
    if phased:
        required.update(decision_capture_rule=CAPTURE_RULE, decision_selection_rule=SELECTION_RULE)
    elif any(key in plan for key in ("decision_capture_rule", "decision_selection_rule")):
        raise ValueError("legacy v5 plan cannot declare phased decision rules")
    if any(plan.get(key) != value for key, value in required.items()):
        raise ValueError("decision periods, strategies or source rule differ from supported policy")
    policy = DecisionPolicy(**plan["decision_policy"])
    if asdict(policy) != plan["decision_policy"]:
        raise ValueError("decision policy must declare all fields")
    return policy


def validate_decision_binding(periods: tuple[ProtocolPeriod, ...], selection: SelectionRule,
                               policy: DecisionPolicy | None) -> None:
    if policy is None:
        return
    by_name = {period.name: period for period in periods}
    if ("development" not in by_name or "validation" not in by_name
            or by_name["development"].purpose != "development_selection"
            or by_name["validation"].purpose != "validation_check"
            or by_name["development"].end >= by_name["validation"].start):
        raise ValueError("executable decisions require ordered development-selection and validation-check periods")
    if (selection.development_objective != policy.development_objective
            or selection.minimum_completed_trades != policy.minimum_completed_trades):
        raise ValueError("selection summary differs from executable decision policy")


def decision_budgets(protocol: StudyProtocol) -> tuple[CandidateBudget, ...]:
    policy = policy_from_plan(protocol.analysis_plan_json)
    if policy is None:
        raise ValueError("protocol has no executable decision policy")
    validate_decision_binding(protocol.periods, protocol.selection, policy)
    return tuple(CandidateBudget(candidate.candidate_id, tuple(
        row.scenario_id for row in declared_scenarios(protocol.analysis_plan_json, candidate.candidate_id)))
        for candidate in protocol.candidates)
