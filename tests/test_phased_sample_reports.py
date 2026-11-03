"""Actual registered v6 reports derive the29/30 sample gate without editing summaries."""
import json
from dataclasses import asdict

import pandas as pd
import pytest
from decision_fixtures import run_candidate
from phased_fixtures import phased_fixture, publish, save_selection
from phased_sample_boundaries import sample_boundary_targets

from quant_fund_lab.odd_lot_decisions.phased_reporting import verify_phased_decision_report
from quant_fund_lab.odd_lot_study import load_frozen_odd_lot_study


@pytest.mark.parametrize("development,validation,status", [
    (29, 30, "insufficient_sample"), (30, 29, "insufficient_sample"), (30, 30, "continue")])
def test_v6_actual_report_episode_boundary_preserves_selection_and_declared_scenarios(
    tmp_path, monkeypatch, development, validation, status
):
    studies, protocol, frozen, _, _ = phased_fixture(tmp_path, monkeypatch, positive=True)
    data, _ = load_frozen_odd_lot_study(studies[0])
    periods = {period.name: period for period in protocol.periods}
    anchors = tuple(str(data.close.index[int(data.close.index.searchsorted(
        pd.Timestamp(periods[name].start)))-1].date()) for name in ("development", "validation"))
    monkeypatch.setattr("quant_fund_lab.odd_lot_research._targets",
                        sample_boundary_targets(development, validation, signal_starts=anchors))
    run = run_candidate(tmp_path, protocol, frozen)
    assert run.attempt.status == "succeeded"
    comparison = pd.read_csv(run.report / "comparison.csv")
    for period, expected in (("development", development), ("validation", validation)):
        selected = comparison.loc[comparison.period.eq(period) & comparison.strategy.isin(["ensemble", "momentum"])]
        assert len(selected) == 2 and selected.closed_count.eq(expected).all()
    saved = save_selection(tmp_path, frozen)
    before = {p: p.read_bytes() for p in saved.directory.rglob("*") if p.is_file()}
    result = publish(tmp_path, saved)
    assert result.decision.status == status
    if development == 29:
        assert saved.inputs.selection.selected_candidate is None
        assert result.decision.selected_candidate is None
        assert json.loads((result.report / "evidence.json").read_text()) is None
    else:
        assert result.decision.selected_candidate == saved.inputs.selection.selected_candidate
        assert result.decision.selected_strategy == saved.inputs.selection.selected_strategy
        evidence = json.loads((result.report / "evidence.json").read_text())
        assert evidence["development"]["completed_episodes"] == development
        assert evidence["validation"]["completed_episodes"] == validation
        assert evidence["validation_benchmark"]["completed_episodes"] == 0
        expected = json.loads(protocol.analysis_plan_json)["scenarios_by_candidate"][protocol.candidates[0].candidate_id]
        assert len(evidence["sensitivity"]) == len(expected)
        assert all(row["result"]["completed_episodes"] == validation for row in evidence["sensitivity"])
    assert verify_phased_decision_report(result.report, registry_path=tmp_path / "registry.sqlite",
                                         studies_directory=tmp_path / "studies")
    assert before == {p: p.read_bytes() for p in before}
    assert asdict(result.decision.policy)["minimum_completed_trades"] == 30
