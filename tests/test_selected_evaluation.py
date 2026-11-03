"""Fixed-choice validation cannot turn favorable second-place evidence into a replacement."""
from dataclasses import replace

import pytest
from test_odd_lot_decisions import BUDGETS, POLICY, PROTOCOL, _evidence, _period

from quant_fund_lab.odd_lot_decisions.development import DevelopmentSelection
from quant_fund_lab.odd_lot_decisions.development_types import (
    DevelopmentEvidence,
    DevelopmentPolicy,
)
from quant_fund_lab.odd_lot_decisions.selected_evaluation import evaluate_selected_development


def _selection(evidence):
    policy = DevelopmentPolicy.from_decision_policy(POLICY, start="2021-01-01", end="2023-12-31")
    return DevelopmentSelection(policy, tuple(row.candidate_id for row in BUDGETS),
        tuple(DevelopmentEvidence(row.candidate_id, row.strategy, row.development.status, row.source_fingerprint,
            **{name:getattr(row.development,name) for name in ("reason", "completed_episodes", "annual_return",
                "max_drawdown", "annual_volatility", "sharpe", "calmar")}) for row in evidence))


def test_validation_failure_keeps_original_selection_and_rejects_replacement_evidence():
    evidence = _evidence()
    selection = _selection(evidence)
    first = replace(evidence[0], validation=_period(annual_return=-.5), sensitivity=())
    result = evaluate_selected_development(PROTOCOL, POLICY, BUDGETS, selection, first)
    assert result.selected_candidate == selection.selected_candidate
    assert result.status == "unavailable"  # Failed return and missing scenarios are both disclosed.
    assert any(check.status == "failed" for check in result.candidates[0].checks)
    assert any(check.status == "unavailable" for check in result.candidates[0].checks)
    with pytest.raises(ValueError, match="saved development choice"):
        evaluate_selected_development(PROTOCOL, POLICY, BUDGETS, selection,
            replace(evidence[2], validation=_period(annual_return=999)))
    with pytest.raises(ValueError, match="development differs"):
        evaluate_selected_development(PROTOCOL, POLICY, BUDGETS, selection,
            replace(first, development=_period(calmar=999)))


def test_no_selection_cannot_accept_validation_or_a_different_budget_or_ranking_policy():
    selection = _selection(_evidence()[:1])
    result = evaluate_selected_development(PROTOCOL, POLICY, BUDGETS, selection, None)
    assert result.status == "incomplete_search" and result.selected_candidate is None
    with pytest.raises(ValueError, match="without a development choice"):
        evaluate_selected_development(PROTOCOL, POLICY, BUDGETS, selection, _evidence()[0])
    with pytest.raises(ValueError, match="budget differs"):
        evaluate_selected_development(PROTOCOL, POLICY, BUDGETS[:1], selection, None)
    with pytest.raises(ValueError, match="ranking"):
        evaluate_selected_development(PROTOCOL, replace(POLICY, development_objective="sharpe"),
                                      BUDGETS, selection, None)
