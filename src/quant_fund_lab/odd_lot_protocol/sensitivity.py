"""Versioned opt-in for matched strategy/ETF sensitivity execution."""
from __future__ import annotations

from ..odd_lot_sensitivity.types import SENSITIVITY_RULE, SensitivityScenario
from .types import json_object


def sensitivity_enabled(plan_json: str) -> bool:
    plan = json_object(plan_json)
    if plan.get("engine") in {"frozen_odd_lot_batch_v1", "frozen_odd_lot_batch_v2", "frozen_odd_lot_batch_v3"}:
        if "sensitivity_execution_rule" in plan:
            raise ValueError("legacy analysis plan cannot declare matched sensitivity")
        return False
    if plan.get("engine") in {"frozen_odd_lot_batch_v4", "frozen_odd_lot_batch_v5", "frozen_odd_lot_batch_v6"} and plan.get("sensitivity_execution_rule") == SENSITIVITY_RULE:
        return True
    raise ValueError("unsupported protocol sensitivity plan")


def declared_scenarios(plan_json: str, candidate_id: str) -> tuple[SensitivityScenario, ...]:
    if not sensitivity_enabled(plan_json):
        raise ValueError("matched sensitivity was not declared")
    values = json_object(plan_json)["scenarios_by_candidate"][candidate_id]
    scenarios = tuple(SensitivityScenario(*row) for row in values)
    if not scenarios or len({row.scenario_id for row in scenarios}) != len(scenarios):
        raise ValueError("sensitivity scenario set is empty or duplicated")
    return scenarios
