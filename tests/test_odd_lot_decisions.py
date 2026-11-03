"""Development ranking is frozen before validation, with complete gate/failure disclosure."""
from dataclasses import replace

import pytest

from quant_fund_lab.odd_lot_decisions import (
    CandidateBudget,
    CandidateEvidence,
    DecisionPolicy,
    PeriodEvidence,
    ScenarioEvidence,
    evaluate_research_decision,
)

PROTOCOL = "e"*64
A, B = "1"*64, "2"*64
SCENARIOS = ("a"*64,"b"*64)
BUDGETS = (CandidateBudget(A,SCENARIOS),CandidateBudget(B,SCENARIOS))
POLICY = DecisionPolicy("calmar",.20,0,0,.25)


def _period(**kwargs):
    values = {"status":"available","completed_episodes":40,"annual_return":.2,"total_return":.2,
        "max_drawdown":-.1,"annual_volatility":.15,"sharpe":1.5,"calmar":2.0,
        "risk_evidence_complete":True,"maximum_loss_to_budget_ratio":1.0,
        "maximum_stop_delay_sessions":1,"pending_stop_episodes":0}
    return PeriodEvidence(**{**values,**kwargs})


def _evidence():
    benchmark = PeriodEvidence("available",total_return=.1,completed_episodes=0)
    return tuple(CandidateEvidence(candidate,strategy,_period(calmar=score),_period(),benchmark,
        tuple(ScenarioEvidence(scenario,_period()) for scenario in SCENARIOS),"f"*64)
        for candidate,strategy,score in ((A,"ensemble",2),(A,"momentum",1.8),(B,"ensemble",1.5),(B,"momentum",1.3)))


def _run(evidence=None, policy=POLICY):
    return evaluate_research_decision(PROTOCOL,policy,BUDGETS,evidence if evidence is not None else _evidence())


def test_development_winner_passes_explicit_validation_without_requiring_etf_closed_trades():
    result = _run()
    assert (result.selected_candidate,result.selected_strategy,result.status) == (A,"ensemble","continue")
    assert all(check.status == "passed" for check in result.candidates[0].checks)
    assert [row.status for row in result.candidates] == ["continue","not_selected","not_selected","not_selected"]
    assert result.decision_id == _run(tuple(reversed(_evidence()))).decision_id
    assert result.to_dict()["limitations"] and result.policy.minimum_completed_trades == 30


def test_validation_or_sensitivity_cannot_choose_another_candidate_after_failure():
    evidence = list(_evidence())
    evidence[0] = replace(evidence[0],validation=_period(annual_return=-.2,calmar=-999,total_return=-.1))
    evidence[2] = replace(evidence[2],validation=_period(annual_return=10,calmar=999,total_return=10))
    result = _run(tuple(evidence))
    assert result.status == "return" and result.selected_candidate == A and result.selected_strategy == "ensemble"
    assert "validation_annual_return_outside_bound" in result.reasons
    assert "same_cost_validation_benchmark_not_outperformed" in result.reasons
    assert result.candidates[2].status == "not_selected"


def test_known_rejections_remain_visible_beside_missing_scenario_evidence():
    evidence = list(_evidence())
    evidence[0] = replace(evidence[0],validation=_period(annual_return=-.1),sensitivity=evidence[0].sensitivity[:1])
    result = _run(tuple(evidence))
    assert result.status == "unavailable" and result.selected_candidate == A
    assert any("required_sensitivity_scenario_missing" in reason for reason in result.reasons)
    assert "validation_annual_return_outside_bound" in result.reasons
    assert any(check.status == "failed" for check in result.candidates[0].checks)
    assert any(check.status == "unavailable" for check in result.candidates[0].checks)


def test_missing_development_candidate_blocks_selection_despite_other_good_results():
    result = _run(_evidence()[:2])
    assert result.status == "incomplete_search" and result.selected_candidate is None
    assert len(result.candidates) == 4 and result.candidates[-1].status == "unavailable"
    empty = _run(())
    assert empty.status == "incomplete_search" and len(empty.candidates) == 4
    assert all(row.status == "unavailable" for row in empty.candidates)


def test_small_development_sample_is_known_ineligible_instead_of_unknown_search():
    evidence = tuple(replace(row,development=_period(completed_episodes=10)) for row in _evidence())
    result = _run(evidence)
    assert result.status == "insufficient_sample" and result.selected_candidate is None
    evidence = list(evidence)
    evidence[2] = replace(evidence[2],development=_period(completed_episodes=30))
    assert _run(tuple(evidence)).selected_candidate == B


@pytest.mark.parametrize("objective,changes,reason",[
    ("calmar",{"max_drawdown":0},"calmar_undefined_without_drawdown"),
    ("sharpe",{"annual_volatility":0},"sharpe_undefined_without_variation"),
    ("annual_return",{"annual_return":None},"development_objective_undefined"),
])
def test_undefined_objectives_are_not_zero_ranked(objective,changes,reason):
    evidence = list(_evidence())
    evidence[0] = replace(evidence[0],development=_period(**changes))
    result = _run(tuple(evidence),replace(POLICY,development_objective=objective))
    assert result.status == "incomplete_search" and result.selected_candidate is None
    assert reason in result.candidates[0].reasons


def test_tie_break_uses_candidate_then_strategy_and_not_validation_performance():
    evidence = tuple(replace(row,development=_period(calmar=2)) for row in _evidence())
    result = _run(tuple(reversed(evidence)))
    assert (result.selected_candidate,result.selected_strategy) == (A,"ensemble")


@pytest.mark.parametrize("source",["validation","scenario"])
def test_validation_and_every_scenario_require_closed_episode_sample(source):
    evidence = list(_evidence())
    if source == "validation":
        evidence[0] = replace(evidence[0],validation=_period(completed_episodes=29))
    else:
        evidence[0] = replace(evidence[0],sensitivity=(ScenarioEvidence(SCENARIOS[0],_period(completed_episodes=29)),
                                                   evidence[0].sensitivity[1]))
    result = _run(tuple(evidence))
    assert result.status == "insufficient_sample" and result.selected_candidate == A


def test_failed_scenario_is_unavailable_not_a_bad_return_or_removed_trial():
    evidence = list(_evidence())
    evidence[0] = replace(evidence[0],sensitivity=(ScenarioEvidence(SCENARIOS[0],PeriodEvidence("failed","injected failure")),
                                               evidence[0].sensitivity[1]))
    result = _run(tuple(evidence))
    assert result.status == "unavailable" and any("injected failure" in reason for reason in result.reasons)


def test_risk_thresholds_need_complete_budget_and_pending_exit_evidence():
    policy = replace(POLICY,maximum_loss_to_budget_ratio=1.5,maximum_stop_delay_sessions=2)
    assert _run(policy=policy).status == "continue"
    evidence = list(_evidence())
    evidence[0] = replace(evidence[0],validation=_period(maximum_loss_to_budget_ratio=8,maximum_stop_delay_sessions=3))
    result = _run(tuple(evidence),policy)
    assert result.status == "return" and len(result.reasons) == 2
    evidence[0] = replace(evidence[0],validation=_period(pending_stop_episodes=1,risk_evidence_complete=False))
    assert _run(tuple(evidence),policy).status == "insufficient_sample"
    evidence[0] = replace(evidence[0],validation=_period(risk_evidence_complete=False))
    assert _run(tuple(evidence),policy).status == "unavailable"


def test_boundaries_and_same_cost_benchmark_tie_are_explicit():
    evidence = list(_evidence())
    evidence[0] = replace(evidence[0],validation=_period(annual_return=0,max_drawdown=-.2,total_return=.1))
    result = _run(tuple(evidence))
    assert result.status == "return" and result.reasons == ("same_cost_validation_benchmark_not_outperformed",)
    assert _run(tuple(evidence),replace(POLICY,require_benchmark_outperformance=False)).status == "continue"


def test_foreign_or_duplicate_evidence_cannot_expand_frozen_budget():
    evidence = _evidence()
    for invalid in (evidence + (evidence[0],), (replace(evidence[0],candidate_id="3"*64),)):
        with pytest.raises(ValueError):
            _run(invalid)
    with pytest.raises(ValueError,match="undeclared sensitivity"):
        _run((replace(evidence[0],sensitivity=(ScenarioEvidence("c"*64,_period()),)),)+evidence[1:])


@pytest.mark.parametrize("changes",[{"maximum_validation_drawdown":float("inf")},
    {"minimum_completed_trades":29},{"maximum_sensitivity_drawdown":1.1},
    {"maximum_stop_delay_sessions":True},{"maximum_loss_to_budget_ratio":-1}])
def test_policies_reject_implicit_invalid_or_nonfinite_thresholds(changes):
    with pytest.raises(ValueError):
        replace(POLICY,**changes)


def test_unavailable_or_nonfinite_metrics_cannot_masquerade_as_valid_evidence():
    with pytest.raises(ValueError):
        _period(total_return=float("nan"))
    with pytest.raises(ValueError,match="invented metrics"):
        PeriodEvidence("blocked","missing data",completed_episodes=0)


def test_missing_same_cost_comparator_does_not_borrow_another_candidate_benchmark():
    evidence = list(_evidence())
    evidence[0] = replace(evidence[0],validation_benchmark=PeriodEvidence("blocked","missing ETF inputs"))
    result = _run(tuple(evidence))
    assert result.status == "unavailable" and result.selected_candidate == A
    assert "same_cost_validation_benchmark_unavailable" in result.reasons
