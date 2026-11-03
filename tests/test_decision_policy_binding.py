"""Executable policy identities and period gates before candidate evaluation."""
from dataclasses import replace

import pytest
from protocol_fixtures import protocol

from quant_fund_lab.odd_lot_benchmarks import BenchmarkSpec
from quant_fund_lab.odd_lot_decisions import DecisionPolicy
from quant_fund_lab.odd_lot_protocol.build import analysis_plan
from quant_fund_lab.odd_lot_protocol.decision import (
    decision_budgets,
    policy_from_plan,
    validate_decision_binding,
)
from quant_fund_lab.odd_lot_protocol.types import ProtocolPeriod, canonical_json


def _spec(policy=None):
    original = protocol()
    candidate = replace(original.candidates[0], research_json=canonical_json({
        "fill_fraction": .5, "min_commission": 20, "slippage_bps": 5,
    }))
    periods = (ProtocolPeriod("development", "2021-01-01", "2023-12-31",
        "development_selection", "accessed", "Synthetic retrospective fixture."),
        *original.periods)
    plan = analysis_plan((candidate,), BenchmarkSpec("0050.TW", 100000, 10, .1,
        "Synthetic assumptions only."), risk_diagnostics=True,
        matched_sensitivity=True, decision_policy=policy)
    return replace(original, candidates=(candidate,), periods=periods,
                   analysis_plan_json=canonical_json(plan))


POLICY = DecisionPolicy("calmar", .2, 0, 0, .25)


def test_legacy_plan_remains_without_policy_and_rejects_injected_policy():
    legacy = _spec()
    assert policy_from_plan(legacy.analysis_plan_json) is None
    with pytest.raises(ValueError, match="no executable"):
        decision_budgets(legacy)
    import json
    plan = json.loads(legacy.analysis_plan_json)
    plan["decision_policy"] = {}
    with pytest.raises(ValueError, match="legacy"):
        policy_from_plan(canonical_json(plan))


def test_policy_threshold_changes_identity_and_preserves_candidate_budget():
    first = _spec(POLICY)
    second = _spec(replace(POLICY, maximum_validation_drawdown=.19))
    assert first.protocol_id != second.protocol_id
    assert first.candidates == second.candidates
    assert policy_from_plan(first.analysis_plan_json) == POLICY
    budgets = decision_budgets(first)
    assert len(budgets) == 1 and budgets[0].candidate_id == first.candidates[0].candidate_id
    assert budgets[0].scenario_ids and len(set(budgets[0].scenario_ids)) == len(budgets[0].scenario_ids)


@pytest.mark.parametrize("field,value", [("development_objective", "sharpe"),
                                        ("minimum_completed_trades", 31)])
def test_selection_summary_must_match_policy(field, value):
    spec = _spec(POLICY)
    with pytest.raises(ValueError, match="summary"):
        validate_decision_binding(spec.periods, replace(spec.selection, **{field: value}), POLICY)


def test_validation_cannot_be_repurposed_for_development_selection():
    spec = _spec(POLICY)
    wrong = (spec.periods[0], replace(spec.periods[1], purpose="development_selection"))
    with pytest.raises(ValueError, match="ordered"):
        validate_decision_binding(wrong, spec.selection, POLICY)


def test_serialized_policy_requires_all_fields_including_optional_gate_choices():
    import json
    plan = json.loads(_spec(POLICY).analysis_plan_json)
    del plan["decision_policy"]["require_benchmark_outperformance"]
    with pytest.raises(ValueError, match="all fields"):
        policy_from_plan(canonical_json(plan))


@pytest.mark.parametrize("key,value", [
    ("decision_ranking_period", "validation"),
    ("decision_validation_period", "historical"),
    ("decision_strategies", ["equal_weight"]),
    ("decision_source_rule", "best_successful_attempt"),
])
def test_policy_reader_rejects_changed_selection_or_evidence_semantics(key, value):
    import json
    plan = json.loads(_spec(POLICY).analysis_plan_json)
    plan[key] = value
    with pytest.raises(ValueError, match="source rule"):
        policy_from_plan(canonical_json(plan))
