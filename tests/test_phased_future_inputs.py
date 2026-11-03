"""V6 saved selections remain development-only when genuine future inputs change."""
from pathlib import Path

import pandas as pd
from decision_fixtures import run_candidate
from phased_fixtures import phased_fixture, publish, save_selection
from test_research_browser import _inventory

from quant_fund_lab.odd_lot_decisions.phased_reporting import verify_phased_decision_report


def test_v6_future_prices_change_validation_but_not_persisted_development_selection(tmp_path, monkeypatch):
    import quant_fund_lab.odd_lot_decisions.development_accounts as accounts

    baseline = tmp_path / "baseline"
    baseline.mkdir()
    _, protocol, frozen, _, _ = phased_fixture(baseline, monkeypatch, positive=True, exploration=True)
    first_run = run_candidate(baseline, protocol, frozen)
    cutoff = pd.Timestamp(next(period.end for period in protocol.periods if period.name == "development"))
    original_read, original_sql, original_text = accounts._read_frame, pd.read_sql_query, Path.read_text
    parsed, queried = [], []
    forbidden = {"comparison.csv", "matched_sensitivity.json", "risk_diagnostics.json",
                 "execution_summary.csv", "unavailable.json"}

    def read(path, **kwargs):
        assert path.name.startswith("development_")
        parsed.append(path.name)
        return original_read(path, **kwargs)

    def sql(query, connection, **kwargs):
        assert kwargs["params"][0].startswith("development/")
        queried.append(kwargs["params"][0])
        return original_sql(query, connection, **kwargs)

    def text(path, *args, **kwargs):
        if path.parent == first_run.report:
            assert path.name not in forbidden
            assert not path.name.startswith(("validation_", "exploration_", "scenario_"))
        return original_text(path, *args, **kwargs)

    with monkeypatch.context() as spy:
        spy.setattr(accounts, "_read_frame", read)
        spy.setattr(pd, "read_sql_query", sql)
        spy.setattr(Path, "read_text", text)
        first_saved = save_selection(baseline, frozen)
    assert parsed and queried and len(set(parsed)) == 16
    first = first_saved.inputs.selection
    assert first.status == "selected" and all(row.completed_episodes >= 30 for row in first.evidence)
    assert (first_saved.directory / "selection_manifest.json").is_file()
    first_report = publish(baseline, first_saved)
    retained = _inventory(first_saved.directory)

    future = tmp_path / "future"
    future.mkdir()
    _, other, other_frozen, _, _ = phased_fixture(future, monkeypatch, positive=True, exploration=True,
        prices=lambda day: "10000" if day <= cutoff else str(10000 + day.day * 37))
    second_run = run_candidate(future, other, other_frozen)
    second_saved = save_selection(future, other_frozen)
    second_report = publish(future, second_saved)
    assert protocol.protocol_id != other.protocol_id and protocol.dataset_id != other.dataset_id
    assert first_run.attempt.result_fingerprint != second_run.attempt.result_fingerprint
    assert first.to_dict() == second_saved.inputs.selection.to_dict()
    assert first.selection_id == second_saved.inputs.selection.selection_id
    assert first_saved.capture_fingerprint != second_saved.capture_fingerprint
    assert _inventory(first_saved.directory) == retained
    assert first_report.decision.selected_candidate == second_report.decision.selected_candidate == first.selected_candidate
    assert first_report.decision.selected_strategy == second_report.decision.selected_strategy == first.selected_strategy
    assert not pd.read_csv(first_run.report / "validation_ensemble_equity_curve.csv").equals(
        pd.read_csv(second_run.report / "validation_ensemble_equity_curve.csv"))
    for root, report in [(baseline, first_report), (future, second_report)]:
        assert verify_phased_decision_report(report.report, registry_path=root / "registry.sqlite",
                                             studies_directory=root / "studies")
