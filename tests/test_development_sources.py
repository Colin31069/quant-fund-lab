"""Registered development accounts are authenticated before any validation business parsing."""
import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest
from decision_fixtures import decision_fixture, run_candidate
from test_registered_decisions import _rehash

from quant_fund_lab.odd_lot_decisions.development_registry import collect_registered_development
from quant_fund_lab.odd_lot_decisions.development_source_types import DevelopmentInputs
from quant_fund_lab.odd_lot_decisions.registry_evidence import collect_decision_inputs
from quant_fund_lab.odd_lot_protocol import ExperimentRegistry
from quant_fund_lab.odd_lot_study import verify_odd_lot_study_report


def _collect(root, frozen, **kwargs):
    return collect_registered_development(frozen, registry_path=root / "registry.sqlite",
                                          studies_directory=root / "studies", **kwargs)


def test_actual_future_input_changes_preserve_development_selection_and_never_parse_other_accounts(tmp_path, monkeypatch):
    import quant_fund_lab.odd_lot_decisions.development_accounts as accounts

    baseline = tmp_path / "baseline"
    baseline.mkdir()
    _, protocol, frozen, _ = decision_fixture(baseline, monkeypatch, positive=True, exploration=True)
    run = run_candidate(baseline, protocol, frozen)
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
        if path.parent == run.report:
            assert path.name not in forbidden and not path.name.startswith(("validation_", "exploration_", "scenario_"))
        return original_text(path, *args, **kwargs)
    with monkeypatch.context() as spy:
        spy.setattr(accounts, "_read_frame", read)
        spy.setattr(pd, "read_sql_query", sql)
        spy.setattr(Path, "read_text", text)
        first = _collect(baseline, frozen)
    assert first.selection.status == "selected"
    assert all(row.completed_episodes >= 30 for row in first.selection.evidence)
    assert len(parsed) == 16 and queried
    assert first.to_dict()["source_rule"] == "development_accounts_from_latest_prefix_v1"
    changed = tmp_path / "future"
    changed.mkdir()
    _, other, other_frozen, _ = decision_fixture(changed, monkeypatch, positive=True, exploration=True,
        prices=lambda day: "10000" if day <= cutoff else str(10000 + day.day * 37))
    other_run = run_candidate(changed, other, other_frozen)
    second = _collect(changed, other_frozen)
    assert protocol.dataset_id != other.dataset_id and protocol.protocol_id != other.protocol_id
    assert first.sources[0].attempts[-1].result_fingerprint != second.sources[0].attempts[-1].result_fingerprint
    assert first.selection.to_dict() == second.selection.to_dict()
    assert first.selection.selection_id == second.selection.selection_id
    assert verify_odd_lot_study_report(run.report) and verify_odd_lot_study_report(other_run.report)
    old_validation = pd.read_csv(run.report / "validation_ensemble_equity_curve.csv")
    new_validation = pd.read_csv(other_run.report / "validation_ensemble_equity_curve.csv")
    assert not old_validation.equals(new_validation)


def test_changed_warmup_input_changes_development_identity_without_fabricating_trades(tmp_path, monkeypatch):
    first_root, second_root = tmp_path / "first", tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    _, protocol, frozen, _ = decision_fixture(first_root, monkeypatch)
    run_candidate(first_root, protocol, frozen)
    first = _collect(first_root, frozen)
    _, changed, changed_frozen, _ = decision_fixture(second_root, monkeypatch,
        prices=lambda day: "101" if str(day.date()) == "2023-01-03" else "100")
    run_candidate(second_root, changed, changed_frozen)
    second = _collect(second_root, changed_frozen)
    assert first.selection.status == second.selection.status == "insufficient_sample"
    assert first.selection.selected_candidate is second.selection.selected_candidate is None
    assert first.selection.selection_id != second.selection.selection_id
    assert all(row.completed_episodes == 0 for row in first.selection.evidence + second.selection.evidence)


def test_missing_running_failed_and_historical_prefix_keep_complete_budget(tmp_path, monkeypatch):
    _, protocol, frozen, _ = decision_fixture(tmp_path, monkeypatch, count=2)
    missing = _collect(tmp_path, frozen)
    assert missing.selection.status == "incomplete_search" and len(missing.selection.candidates) == 4
    run = run_candidate(tmp_path, protocol, frozen)
    partial = _collect(tmp_path, frozen)
    assert partial.selection.status == "incomplete_search"
    run_candidate(tmp_path, protocol, frozen, protocol.candidates[1].candidate_id)
    complete = _collect(tmp_path, frozen)
    assert complete.selection.status == "insufficient_sample"
    assert _collect(tmp_path, frozen, snapshot=missing.sources) == missing
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        attempt = registry.start_attempt(run.experiment.experiment_id)
    running = _collect(tmp_path, frozen)
    assert running.selection.status == "incomplete_search"
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        registry.finish_attempt(run.experiment.experiment_id, attempt.attempt, status="failed", reason="source unavailable")
    failed = _collect(tmp_path, frozen)
    assert failed.selection.status == "incomplete_search"
    assert any("source unavailable" in row.reason for row in failed.selection.evidence)
    assert _collect(tmp_path, frozen, snapshot=running.sources) == running
    assert _collect(tmp_path, frozen, snapshot=complete.sources) == complete
    with pytest.raises(ValueError, match="complete candidate budget"):
        _collect(tmp_path, frozen, snapshot=complete.sources[:1])
    with pytest.raises(ValueError, match="inventory"):
        DevelopmentInputs(complete.sources[:1], complete.selection)


@pytest.mark.parametrize("artifact", ["csv", "archive", "settings", "context", "path"])
def test_rehashed_development_source_tampering_is_rejected(tmp_path, monkeypatch, artifact):
    _, protocol, frozen, _ = decision_fixture(tmp_path, monkeypatch)
    run = run_candidate(tmp_path, protocol, frozen)
    if artifact == "csv":
        path = run.report / "development_ensemble_equity_curve.csv"
        frame = pd.read_csv(path)
        frame.loc[1, "equity"] += 999
        frame.to_csv(path, index=False)
    elif artifact in {"archive", "settings"}:
        path = run.report / "study_ledger.sqlite"
        with sqlite3.connect(path) as db:
            if artifact == "archive":
                db.execute("UPDATE equity_curve SET equity=equity+999 WHERE account_id='development/ensemble'")
            else:
                db.execute("DROP TRIGGER no_account_update")
                db.execute("UPDATE accounts SET settings_json='{}' WHERE account_id='development/ensemble'")
    else:
        path = run.report / "experiment.json"
        context = json.loads(path.read_text())
        context["attempt"] += 1
        path.write_text(json.dumps(context))
    _rehash(run.report, path)
    if artifact == "path":
        manifest_path = run.report / "report_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["../escape"] = "f" * 64
        from quant_fund_lab.odd_lot_decisions.types import fingerprint
        manifest.pop("report_id")
        manifest["report_id"] = fingerprint(manifest)
        manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        _collect(tmp_path, frozen)


def test_failed_validation_scenario_does_not_change_valid_development_identity(tmp_path, monkeypatch):
    from quant_fund_lab.odd_lot_sensitivity import engine

    _, protocol, frozen, _ = decision_fixture(tmp_path, monkeypatch, positive=True)
    original = engine.run_tradable_benchmark
    def fail(data, spec, research, *args, **kwargs):
        if research.min_commission == 50:
            raise ValueError("required validation ETF scenario failed")
        return original(data, spec, research, *args, **kwargs)
    monkeypatch.setattr(engine, "run_tradable_benchmark", fail)
    with pytest.raises(ValueError, match="sensitivity scenarios failed"):
        run_candidate(tmp_path, protocol, frozen)
    failed = _collect(tmp_path, frozen)
    assert failed.sources[0].attempts[-1].status == "failed" and failed.selection.status == "selected"
    monkeypatch.setattr(engine, "run_tradable_benchmark", original)
    run_candidate(tmp_path, protocol, frozen)
    passed = _collect(tmp_path, frozen)
    assert [row.status for row in passed.sources[0].attempts] == ["failed", "succeeded"]
    assert failed.selection.selection_id == passed.selection.selection_id


def test_registry_change_during_collection_is_rejected(tmp_path, monkeypatch):
    import quant_fund_lab.odd_lot_decisions.development_registry as module

    _, protocol, frozen, _ = decision_fixture(tmp_path, monkeypatch)
    run = run_candidate(tmp_path, protocol, frozen)
    original = module.report_development_evidence
    def race(*args, **kwargs):
        rows = original(*args, **kwargs)
        with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
            registry.start_attempt(run.experiment.experiment_id)
        return rows
    monkeypatch.setattr(module, "report_development_evidence", race)
    with pytest.raises(ValueError, match="changed during collection"):
        _collect(tmp_path, frozen)


def test_nonreproducible_history_cannot_be_erased_by_a_later_consistent_retry(tmp_path, monkeypatch):
    _, protocol, frozen, _ = decision_fixture(tmp_path, monkeypatch)
    run = run_candidate(tmp_path, protocol, frozen)
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        attempt = registry.start_attempt(run.experiment.experiment_id)
        failed = registry.finish_attempt(run.experiment.experiment_id, attempt.attempt,
            status="succeeded", result_fingerprint="f" * 64)
        assert failed.status == "failed" and failed.reason.startswith("nonreproducible numerical result")
    run_candidate(tmp_path, protocol, frozen)
    result = _collect(tmp_path, frozen)
    assert [row.status for row in result.sources[0].attempts] == ["succeeded", "failed", "succeeded"]
    assert result.selection.status == "incomplete_search" and result.selection.selected_candidate is None
    assert all("unresolved nonreproducible" in row.reason for row in result.selection.evidence)


def test_source_byte_change_during_collection_and_symlinked_snapshots_are_rejected(tmp_path, monkeypatch):
    import quant_fund_lab.odd_lot_decisions.development_registry as module

    _, protocol, frozen, _ = decision_fixture(tmp_path, monkeypatch)
    run = run_candidate(tmp_path, protocol, frozen)
    original = module.report_development_evidence
    artifact = run.report / "development_ensemble_equity_curve.csv"
    before = artifact.read_bytes()
    def race(*args, **kwargs):
        result = original(*args, **kwargs)
        artifact.write_bytes(before + b"\n")
        return result
    with monkeypatch.context() as patch:
        patch.setattr(module, "report_development_evidence", race)
        with pytest.raises(ValueError, match="byte integrity"):
            _collect(tmp_path, frozen)
    artifact.write_bytes(before)
    snapshot = tmp_path / "studies" / run.experiment.study_id / "snapshot" / "close.parquet"
    payload = tmp_path / "relocated.parquet"
    snapshot.rename(payload)
    snapshot.symlink_to(payload)
    with pytest.raises(ValueError, match="symlinks"):
        _collect(tmp_path, frozen)


@pytest.mark.parametrize("artifact", ["comparison", "scenario"])
def test_bad_validation_content_does_not_change_development_but_cannot_supply_final_evidence(tmp_path, monkeypatch, artifact):
    _, protocol, frozen, _ = decision_fixture(tmp_path, monkeypatch)
    run = run_candidate(tmp_path, protocol, frozen)
    before = _collect(tmp_path, frozen)
    if artifact == "comparison":
        path = run.report / "comparison.csv"
        frame = pd.read_csv(path)
        frame.loc[frame.period.eq("validation") & frame.strategy.eq("ensemble"), "annual_return"] = 999
        frame.to_csv(path, index=False)
    else:
        path = run.report / "matched_sensitivity.json"
        path.write_text("{invalid validation payload")
    _rehash(run.report, path)
    after = _collect(tmp_path, frozen)
    assert before.selection == after.selection
    assert before.sources != after.sources
    with pytest.raises(ValueError):
        collect_decision_inputs(frozen, registry_path=tmp_path / "registry.sqlite",
                                studies_directory=tmp_path / "studies")
