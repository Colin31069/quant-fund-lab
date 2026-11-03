"""Development identities exclude validation policy and rebuild every derived ranking field."""
import json
from dataclasses import asdict, replace

import pytest

from quant_fund_lab.odd_lot_decisions import (
    CandidateBudget,
    CandidateEvidence,
    DecisionPolicy,
    DevelopmentEvidence,
    DevelopmentPolicy,
    DevelopmentSelection,
    PeriodEvidence,
    evaluate_research_decision,
)
from quant_fund_lab.odd_lot_decisions.types import fingerprint

A, B, SOURCE = "1" * 64, "2" * 64, "f" * 64
POLICY = DevelopmentPolicy("2021-01-01", "2023-12-31", "calmar")


def _evidence():
    return tuple(DevelopmentEvidence(candidate, strategy, "available", SOURCE,
        completed_episodes=30, annual_return=.2, max_drawdown=-.1, annual_volatility=.2,
        sharpe=1, calmar=score) for candidate, strategy, score in (
            (A, "ensemble", 2), (A, "momentum", 1), (B, "ensemble", 3), (B, "momentum", 3)))


def _select(evidence=None, policy=POLICY):
    return DevelopmentSelection(policy, (A, B), _evidence() if evidence is None else evidence)


def test_canonical_round_trip_rebuilds_ranks_and_ties_independently_of_input_order():
    result = _select()
    assert (result.status, result.selected_candidate, result.selected_strategy) == ("selected", B, "ensemble")
    assert [row.rank for row in result.candidates] == [3, 4, 1, 2]
    assert result == DevelopmentSelection.from_dict(json.loads(json.dumps(result.to_dict(), allow_nan=False)))
    assert result.selection_id == DevelopmentSelection(POLICY, (B, A), tuple(reversed(_evidence()))).selection_id
    assert result.selection_id == _select(tuple(replace(row, calmar=float(row.calmar)) for row in _evidence())).selection_id


def test_validation_threshold_changes_are_excluded_from_development_policy_identity():
    original = DecisionPolicy("calmar", .2, 0, 0, .2)
    changed = replace(original, maximum_validation_drawdown=.9, minimum_validation_annual_return=4,
        minimum_sensitivity_total_return=2, maximum_sensitivity_drawdown=.8,
        require_benchmark_outperformance=False, maximum_loss_to_budget_ratio=3, maximum_stop_delay_sessions=5)
    first = DevelopmentPolicy.from_decision_policy(original, start=POLICY.development_start, end=POLICY.development_end)
    second = DevelopmentPolicy.from_decision_policy(changed, start=POLICY.development_start, end=POLICY.development_end)
    assert fingerprint(asdict(original)) != fingerprint(asdict(changed))
    assert first == second == POLICY
    assert _select(policy=first).selection_id == _select(policy=second).selection_id
    assert not any("validation" in key or "sensitivity" in key for key in asdict(first))


def test_changed_development_dependencies_change_identity_even_when_winner_does_not_change():
    original = _select()
    changed_source = tuple(replace(row, source_fingerprint="e" * 64) for row in _evidence())
    changed_score = tuple(replace(row, annual_return=.21) for row in _evidence())
    changed = [_select(changed_source), _select(changed_score),
        _select(policy=replace(POLICY, development_start="2021-01-02")),
        _select(policy=replace(POLICY, minimum_completed_trades=31)),
        DevelopmentSelection(POLICY, (A, B, "3" * 64), _evidence())]
    assert all(row.selection_id != original.selection_id for row in changed)
    assert changed[0].selected_candidate == changed[1].selected_candidate == original.selected_candidate


def test_incomplete_search_preserves_all_declared_rows_without_selecting_partial_best():
    result = _select(_evidence()[:-1])
    assert result.status == "incomplete_search" and result.selected_candidate is None
    assert result.selected_strategy is None and len(result.candidates) == 4
    assert result.candidates[-1].reason == "declared_candidate_evidence_missing"
    assert result.candidates[2].rank == 1  # Provisional rank is not a selection.
    assert _select(()).status == "incomplete_search"


@pytest.mark.parametrize("count,status", [(0, "insufficient_sample"), (29, "insufficient_sample"), (30, "selected")])
def test_known_episode_boundary_is_distinct_from_missing_evidence(count, status):
    result = _select(tuple(replace(row, completed_episodes=count) for row in _evidence()))
    assert result.status == status
    if count < 30:
        assert result.selected_candidate is None and all(row.rank is None for row in result.candidates)


@pytest.mark.parametrize("changes,reason", [
    ({"completed_episodes": None}, "development_episode_count_unknown"),
    ({"calmar": None}, "development_objective_undefined"),
    ({"max_drawdown": 0}, "calmar_undefined_without_drawdown"),
])
def test_undefined_development_values_block_whole_selection(changes, reason):
    evidence = list(_evidence())
    evidence[0] = replace(evidence[0], **changes)
    result = _select(tuple(evidence))
    assert result.status == "incomplete_search" and result.selected_candidate is None
    assert result.candidates[0].reason == reason


def test_sharpe_needs_variation_and_unavailable_reasons_are_retained():
    evidence = list(_evidence())
    evidence[0] = replace(evidence[0], annual_volatility=0)
    result = _select(tuple(evidence), replace(POLICY, development_objective="sharpe"))
    assert result.candidates[0].reason == "sharpe_undefined_without_variation"
    evidence[0] = DevelopmentEvidence(A, "ensemble", "failed", SOURCE, reason="development source lost")
    assert _select(tuple(evidence)).candidates[0].reason == "development_failed: development source lost"


@pytest.mark.parametrize("mutation", ["rank", "winner", "status", "unknown", "version", "reorder"])
def test_outer_rehashed_tampering_does_not_override_reconstructed_selection(mutation):
    payload = _select().to_dict()
    if mutation == "rank":
        payload["candidates"][0]["rank"] = 1
    elif mutation == "winner":
        payload["selected_candidate"] = A
    elif mutation == "status":
        payload["status"] = "continue"
    elif mutation == "unknown":
        payload["validation_return"] = 999
    elif mutation == "version":
        payload["schema_version"] = 2
    else:
        payload["evidence"].reverse()
    assert fingerprint(payload) != _select().selection_id
    with pytest.raises(ValueError, match="reconstructed semantics"):
        DevelopmentSelection.from_dict(payload)


def test_duplicate_foreign_mutable_or_untyped_declarations_are_rejected():
    for ids, evidence in [((A, A), _evidence()), ((A,), _evidence()),
                          ((A, B), _evidence() + (_evidence()[0],)), ((), ()), ([A, B], _evidence())]:
        with pytest.raises(ValueError):
            DevelopmentSelection(POLICY, ids, evidence)
    with pytest.raises(TypeError):
        DevelopmentSelection(POLICY, (A, B), (asdict(_evidence()[0]),))


@pytest.mark.parametrize("changes", [{"calmar": float("nan")}, {"sharpe": float("inf")},
    {"annual_return": True}, {"annual_volatility": -1}, {"completed_episodes": True},
    {"status": "blocked", "reason": "not ready"}, {"strategy": "tradable_etf"}])
def test_invalid_development_evidence_cannot_enter_fingerprint(changes):
    with pytest.raises(ValueError):
        replace(_evidence()[0], **changes)


@pytest.mark.parametrize("changes", [{"development_start": "20210101"}, {"development_end": "2020-01-01"},
    {"minimum_completed_trades": 29}, {"rule_version": "unknown"}, {"tie_break": "best_validation"}])
def test_unsupported_or_ambiguous_development_policy_is_rejected(changes):
    with pytest.raises(ValueError):
        replace(POLICY, **changes)


@pytest.mark.parametrize("objective", ["annual_return", "sharpe", "calmar"])
def test_selection_matches_legacy_ranking_without_changing_legacy_decision_contract(objective):
    policy = DecisionPolicy(objective, .2, 0, 0, .2)
    development_policy = DevelopmentPolicy.from_decision_policy(policy, start=POLICY.development_start, end=POLICY.development_end)
    unavailable = PeriodEvidence("unavailable", "validation not read")
    for count in (29, 30):
        development = tuple(replace(row, completed_episodes=count) for row in _evidence())
        selection = _select(development, development_policy)
        old_evidence = tuple(CandidateEvidence(row.candidate_id, row.strategy,
            PeriodEvidence("available", completed_episodes=row.completed_episodes,
                **{name: getattr(row, name) for name in ("annual_return", "max_drawdown", "annual_volatility", "sharpe", "calmar")}),
            unavailable, unavailable, (), SOURCE) for row in development)
        legacy = evaluate_research_decision("d" * 64, policy,
            tuple(CandidateBudget(identity, ("a" * 64,)) for identity in (A, B)), old_evidence)
        assert (selection.selected_candidate, selection.selected_strategy) == (legacy.selected_candidate, legacy.selected_strategy)
        assert [(row.candidate_id, row.strategy, row.score) for row in selection.candidates] == [
            (row.candidate_id, row.strategy, row.development_score) for row in legacy.candidates]
