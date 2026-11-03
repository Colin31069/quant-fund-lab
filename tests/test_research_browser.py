"""The actual research browser authenticates snapshots without starting research on reruns."""
import hashlib
import json

import pytest
from decision_fixtures import run_candidate
from phased_fixtures import phased_fixture, publish, save_selection
from streamlit.testing.v1 import AppTest
from test_registered_odd_lot_study import SOURCE

from quant_fund_lab.odd_lot_decisions.inspection import inspect_decision, inspect_research
from quant_fund_lab.odd_lot_decisions.types import DecisionPolicy
from quant_fund_lab.odd_lot_protocol import ExperimentRegistry
from quant_fund_lab.odd_lot_protocol.storage import load_protocol


def _inventory(root):
    return {str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file() and path.suffix != '.pyc'}


def _app(root, frozen, mode="僅協議與歷史", artifact=""):
    script = ("import streamlit as st\n"
              "from quant_fund_lab.odd_lot_decisions.ui import render_research_browser\n"
              f"render_research_browser(st, {str(SOURCE)!r})\n")
    app = AppTest.from_string(script).run(timeout=30)
    for label,value in {"研究協議目錄":str(frozen),"實驗登記 SQLite 路徑":str(root / "registry.sqlite"),
                        "研究來源根目錄":str(root / "studies"),"保存產物目錄（選擇或決策）":str(artifact)}.items():
        next(widget for widget in app.text_input if widget.label == label).set_value(value)
    app.selectbox[0].set_value(mode)
    return app


def _read(app):
    next(button for button in app.button if button.label == "核驗並瀏覽研究").click()
    return app.run(timeout=30)


def test_overview_lists_declared_missing_failed_and_running_history_without_writes(tmp_path, monkeypatch):
    _, protocol, frozen, _, _ = phased_fixture(tmp_path,monkeypatch,count=2)
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        experiment = registry.register_experiment(protocol,protocol.candidates[0].candidate_id,protocol.execution)
        first = registry.start_attempt(experiment.experiment_id)
        registry.finish_attempt(experiment.experiment_id,first.attempt,status="failed",reason="injected failure retained")
        registry.start_attempt(experiment.experiment_id)
    before = _inventory(tmp_path)
    overview = inspect_research(frozen,registry_path=tmp_path / "registry.sqlite")
    assert [len(history) for _,history in overview.histories] == [2,0]
    app = _read(_app(tmp_path,frozen))
    assert not app.exception and not app.error
    candidate_table = next(frame.value for frame in app.dataframe if "latest_status" in frame.value.columns)
    assert set(candidate_table.latest_status) == {"running","not_attempted"}
    attempts = next(frame.value for frame in app.dataframe if "started_at" in frame.value.columns)
    assert attempts.status.tolist() == ["failed","running"]
    assert "injected failure retained" in attempts.reason.tolist()
    app.run(timeout=30)
    _read(app)
    assert _inventory(tmp_path) == before


def test_legacy_no_policy_is_visible_and_never_gets_default_thresholds(tmp_path, monkeypatch):
    _, _, _, legacy, _ = phased_fixture(tmp_path,monkeypatch)
    old = load_protocol(legacy)
    no_policy = legacy.parent / old.parent_protocol_id
    before = _inventory(tmp_path)
    app = _read(_app(tmp_path,no_policy))
    assert not app.exception and not app.error
    assert any("未宣告可執行決策政策" in text.value for text in app.info)
    assert not any("已凍結決策政策" in text.value for text in app.markdown)
    assert _inventory(tmp_path) == before


@pytest.mark.parametrize("mode", ["保存的開發選擇","保存的決策"])
def test_verified_incomplete_snapshot_is_displayed_without_new_attempts(tmp_path, monkeypatch, mode):
    _, _, frozen, _, _ = phased_fixture(tmp_path,monkeypatch)
    saved = save_selection(tmp_path,frozen)
    artifact = saved.directory if mode == "保存的開發選擇" else publish(tmp_path,saved).report
    before = _inventory(tmp_path)
    app = _read(_app(tmp_path,frozen,mode,artifact))
    assert not app.exception and not app.error
    assert any("incomplete_search" in text.value for text in app.markdown)
    tables = [frame.value for frame in app.dataframe if "status" in frame.value.columns]
    assert any(set(table.status) == {"unavailable"} for table in tables)
    app.run(timeout=30)
    _read(app)
    assert not app.exception and _inventory(tmp_path) == before


def test_bad_decision_source_is_rejected_without_displaying_metrics_or_mutating_files(tmp_path, monkeypatch):
    _, _, frozen, _, _ = phased_fixture(tmp_path,monkeypatch)
    result = publish(tmp_path,save_selection(tmp_path,frozen))
    path = result.report / "decision.json"
    payload = json.loads(path.read_text())
    payload["decision"]["status"] = "continue"
    path.write_text(json.dumps(payload))
    before = _inventory(tmp_path)
    with pytest.raises(ValueError,match="reconstruction"):
        inspect_decision(frozen,result.report,registry_path=tmp_path / "registry.sqlite",studies_directory=tmp_path / "studies")
    app = _read(_app(tmp_path,frozen,"保存的決策",result.report))
    assert not app.exception and app.error
    assert not app.success
    assert not any("決策狀態：continue" in text.value for text in app.markdown)
    assert _inventory(tmp_path) == before


def test_insufficient_sample_decision_uses_backend_status_in_ui(tmp_path, monkeypatch):
    _, protocol, frozen, _, _ = phased_fixture(tmp_path,monkeypatch)
    run_candidate(tmp_path,protocol,frozen)
    result = publish(tmp_path,save_selection(tmp_path,frozen))
    before = _inventory(tmp_path)
    app = _read(_app(tmp_path,frozen,"保存的決策",result.report))
    assert not app.exception and not app.error
    assert any("insufficient_sample" in text.value for text in app.markdown)
    assert _inventory(tmp_path) == before


def test_main_app_browser_entry_does_not_create_artifacts_on_rerun(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(SOURCE / "src/quant_fund_lab/ui.py")).run(timeout=30)
    next(widget for widget in app.checkbox if widget.label == "零股研究協議與決策瀏覽").set_value(True)
    app.run(timeout=30)
    assert not app.exception
    assert any(widget.label == "研究協議目錄" for widget in app.text_input)
    app.run(timeout=30)
    assert not app.exception and not (tmp_path / "artifacts").exists()


def test_missing_registry_read_does_not_initialize_a_database(tmp_path, monkeypatch):
    _, _, frozen, _, _ = phased_fixture(tmp_path,monkeypatch)
    app = _app(tmp_path,frozen)
    missing = tmp_path / "absent" / "registry.sqlite"
    next(widget for widget in app.text_input if widget.label == "實驗登記 SQLite 路徑").set_value(str(missing))
    _read(app)
    assert not app.exception and app.error
    assert not missing.parent.exists()


def test_blocked_history_and_different_runtime_profile_remain_visible(tmp_path, monkeypatch):
    from dataclasses import replace

    import quant_fund_lab.odd_lot_decisions.ui as module

    _, protocol, frozen, _, _ = phased_fixture(tmp_path,monkeypatch)
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        record = registry.register_experiment(protocol,protocol.candidates[0].candidate_id,protocol.execution)
        attempt = registry.start_attempt(record.experiment_id)
        registry.finish_attempt(record.experiment_id,attempt.attempt,status="blocked",
            result_fingerprint="f" * 64,reason="required real-source coverage remains blocked")
    original = module.capture_execution_identity
    def different(directory):
        execution = original(directory)
        environment = json.loads(execution.environment_json)
        environment["python"] = "different frozen-runtime profile"
        return replace(execution,environment_json=json.dumps(environment,sort_keys=True,separators=(",",":")))
    monkeypatch.setattr(module,"capture_execution_identity",different)
    before = _inventory(tmp_path)
    app = _read(_app(tmp_path,frozen))
    assert not app.exception and not app.error
    assert any("目前環境與凍結環境不同" in text.value for text in app.warning)
    table = next(frame.value for frame in app.dataframe if "latest_status" in frame.value.columns)
    assert table.latest_status.tolist() == ["blocked"]
    history = next(frame.value for frame in app.dataframe if "started_at" in frame.value.columns)
    assert history.reason.tolist() == ["required real-source coverage remains blocked"]
    assert _inventory(tmp_path) == before


@pytest.mark.parametrize("minimum,status", [(-1,"continue"),(.01,"return")])
def test_actual_validated_decision_status_is_not_recomputed_by_ui(tmp_path, monkeypatch, minimum, status):
    policy = DecisionPolicy("annual_return",1,minimum,-1,1,require_benchmark_outperformance=False)
    _, protocol, frozen, _, _ = phased_fixture(tmp_path,monkeypatch,positive=True,policy=policy)
    run_candidate(tmp_path,protocol,frozen)
    result = publish(tmp_path,save_selection(tmp_path,frozen))
    assert result.decision.status == status
    before = _inventory(tmp_path)
    app = _read(_app(tmp_path,frozen,"保存的決策",result.report))
    assert not app.exception and not app.error
    assert any(f"決策狀態：{status}" in text.value for text in app.markdown)
    table = next(frame.value for frame in app.dataframe if "development_score" in frame.value.columns)
    assert table.loc[table.status.eq(status),"candidate_id"].tolist() == [result.decision.selected_candidate]
    app.run(timeout=30)
    assert _inventory(tmp_path) == before
