"""V6 policy changes publish immutable child protocols without reusing old rules."""
import json
from dataclasses import asdict, replace

import pytest
from test_decision_policy_binding import POLICY, _spec
from test_development_selection import _evidence

from quant_fund_lab.odd_lot_benchmarks import BenchmarkSpec
from quant_fund_lab.odd_lot_decisions import DevelopmentPolicy, DevelopmentSelection
from quant_fund_lab.odd_lot_protocol import freeze_protocol, load_protocol
from quant_fund_lab.odd_lot_protocol.build import analysis_plan
from quant_fund_lab.odd_lot_protocol.decision import (
    decision_budgets,
    policy_from_plan,
    validate_decision_binding,
)
from quant_fund_lab.odd_lot_protocol.types import canonical_json

CHANGES = (
    ("maximum_validation_drawdown", .19), ("minimum_validation_annual_return", .01),
    ("minimum_sensitivity_total_return", -.01), ("maximum_sensitivity_drawdown", .24),
    ("require_benchmark_outperformance", False), ("maximum_loss_to_budget_ratio", 2.),
    ("maximum_stop_delay_sessions", 3), ("minimum_completed_trades", 31),
    ("development_objective", "sharpe"),
)


def _phased(policy):
    original = _spec(policy)
    previous = json.loads(original.analysis_plan_json)
    plan = analysis_plan(original.candidates, BenchmarkSpec(**previous["tradable_benchmark"]),
        risk_diagnostics=True, matched_sensitivity=True, decision_policy=policy, phased_decisions=True)
    summary = replace(original.selection, development_objective=policy.development_objective,
                      minimum_completed_trades=policy.minimum_completed_trades)
    validate_decision_binding(original.periods, summary, policy)
    return replace(original, selection=summary, analysis_plan_json=canonical_json(plan))


@pytest.mark.parametrize("field,value", CHANGES)
def test_every_gate_change_freezes_new_v6_child_and_keeps_original_bytes(tmp_path, field, value):
    parent = _phased(POLICY)
    parent_path = freeze_protocol(parent, tmp_path)
    before = {p: p.read_bytes() for p in parent_path.iterdir() if p.is_file()}
    changed_policy = replace(POLICY, **{field: value})
    changed = _phased(changed_policy)
    assert changed.protocol_id != parent.protocol_id  # Isolate policy change from parent linkage.
    child = replace(changed, parent_protocol_id=parent.protocol_id)
    child_path = freeze_protocol(child, tmp_path)
    assert parent_path != child_path and child.protocol_id != parent.protocol_id
    assert load_protocol(parent_path) == parent and load_protocol(child_path) == child
    assert policy_from_plan(child.analysis_plan_json) == changed_policy
    assert child.candidates == parent.candidates and child.max_candidates == parent.max_candidates
    assert decision_budgets(child) == decision_budgets(parent)
    assert json.loads(child.analysis_plan_json)["engine"] == "frozen_odd_lot_batch_v6"
    assert all(p.read_bytes() == content for p, content in before.items())
    first = DevelopmentPolicy.from_decision_policy(POLICY, start="2021-01-01", end="2023-12-31")
    second = DevelopmentPolicy.from_decision_policy(changed_policy, start="2021-01-01", end="2023-12-31")
    evidence = _evidence()
    ids = tuple(sorted({row.candidate_id for row in evidence}))
    base_selection = DevelopmentSelection(first, ids, evidence)
    changed_selection = DevelopmentSelection(second, ids, evidence)
    if field in {"development_objective", "minimum_completed_trades"}:
        assert first != second and base_selection.selection_id != changed_selection.selection_id
    else:
        assert first == second and base_selection.to_dict() == changed_selection.to_dict()
        assert base_selection.selection_id == changed_selection.selection_id


@pytest.mark.parametrize("missing", tuple(asdict(POLICY)))
def test_every_serialized_gate_must_be_declared_in_v6_including_optional_choices(missing):
    plan = json.loads(_phased(POLICY).analysis_plan_json)
    plan["decision_policy"].pop(missing)
    with pytest.raises((ValueError, TypeError)):
        policy_from_plan(canonical_json(plan))
