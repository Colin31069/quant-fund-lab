"""V4 freezes the full matched grid, preserves failures and binds every scenario report."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from test_protocol_diagnostics import _v3
from test_registered_odd_lot_study import SOURCE

from quant_fund_lab.odd_lot_protocol import (
    ExperimentRegistry,
    freeze_protocol,
    protocol_from_studies,
    run_registered_study,
)
from quant_fund_lab.odd_lot_protocol.benchmark import benchmark_from_plan
from quant_fund_lab.odd_lot_protocol.sensitivity import declared_scenarios, sensitivity_enabled
from quant_fund_lab.odd_lot_protocol.types import canonical_json, json_object
from quant_fund_lab.odd_lot_study import verify_odd_lot_study_report


def _v4(tmp_path, monkeypatch, *, ready):
    directory, parent, _ = _v3(tmp_path,monkeypatch,ready=ready)
    benchmark = benchmark_from_plan(parent.analysis_plan_json)
    protocol = protocol_from_studies((directory,),periods=parent.periods,selection=parent.selection,
        execution=parent.execution,declared_at=parent.declared_at,parent_protocol_id=parent.protocol_id,
        benchmark_spec=benchmark,risk_diagnostics=True,matched_sensitivity=True)
    with ExperimentRegistry(tmp_path/"registry.sqlite") as registry:
        registry.register_protocol(parent)
    assert not sensitivity_enabled(parent.analysis_plan_json)
    return directory, protocol, benchmark, freeze_protocol(protocol,tmp_path/"protocols")


def _run(directory, protocol, frozen, tmp_path):
    return run_registered_study(frozen,protocol.candidates[0].candidate_id,studies_directory=directory.parent,
        registry_path=tmp_path/"registry.sqlite",source_directory=SOURCE)


def _rehash(report, artifact):
    path = report/"report_manifest.json"
    manifest = json.loads(path.read_text())
    manifest.pop("report_id")
    manifest["files"][artifact.name] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest["report_id"] = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    path.write_text(canonical_json(manifest))


def test_v4_reports_every_scenario_and_reproduces_accounts(tmp_path, monkeypatch):
    directory, protocol, benchmark, frozen = _v4(tmp_path,monkeypatch,ready=True)
    first = _run(directory,protocol,frozen,tmp_path)
    second = _run(directory,protocol,frozen,tmp_path)
    assert first.attempt.status == second.attempt.status == "succeeded"
    assert first.attempt.result_fingerprint == second.attempt.result_fingerprint
    assert verify_odd_lot_study_report(first.report)
    scenarios = declared_scenarios(protocol.analysis_plan_json,protocol.candidates[0].candidate_id)
    payload = json.loads((first.report/"matched_sensitivity.json").read_text())
    assert len(payload["outcomes"]) == len(scenarios)*3
    assert payload["strategies"] == ["ensemble","momentum",benchmark.result_name]
    for row in payload["outcomes"]:
        assert row["status"] == "succeeded"
        prefix = f"scenario_{row['scenario_id']}_{row['strategy']}"
        settings = json.loads((first.report/f"{prefix}_account.json").read_text())
        assert settings["research"]["fill_fraction"] == row["fill_fraction"]
        assert settings["execution"]["tw_costs"]["slippage_bps"] == row["slippage_bps"]
        assert (first.report/f"{prefix}_settlements.csv").exists()
    assert len(pd.read_csv(first.report/"sensitivity.csv")) == len(scenarios)*3
    assert "策略與可交易基準敏感度" in (first.report/"report.html").read_text()
    assert json_object(protocol.analysis_plan_json)["automatic_candidate_selection"] is False
    path = first.report/"matched_sensitivity.json"
    payload["outcomes"].pop()
    path.write_text(canonical_json(payload))
    _rehash(first.report,path)
    assert not verify_odd_lot_study_report(first.report)


def test_blocked_grid_is_explicit_and_never_computes_sensitivity(tmp_path, monkeypatch):
    directory, protocol, _, frozen = _v4(tmp_path,monkeypatch,ready=False)
    import quant_fund_lab.odd_lot_sensitivity.engine as module

    def forbidden(*args,**kwargs):
        pytest.fail("blocked scenario reached matching")
    monkeypatch.setattr(module,"run_tradable_benchmark",forbidden)
    monkeypatch.setattr(module,"run_odd_lot_research",forbidden)
    result = _run(directory,protocol,frozen,tmp_path)
    assert result.attempt.status == "blocked" and verify_odd_lot_study_report(result.report)
    payload = json.loads((result.report/"matched_sensitivity.json").read_text())
    assert all(row["status"] == "blocked" and row["summaries"] == {} for row in payload["outcomes"])
    assert not list(result.report.glob("scenario_*"))
    assert len(json.loads((result.report/"unavailable.json").read_text())) == 15
    assert (result.report/"comparison.csv").read_text().strip() == ""
    assert pd.read_csv(result.report/"sensitivity.csv").status.eq("blocked").all()


def test_failed_scenario_report_and_attempt_survive_successful_retry(tmp_path, monkeypatch):
    directory, protocol, _, frozen = _v4(tmp_path,monkeypatch,ready=True)
    import quant_fund_lab.odd_lot_sensitivity.engine as module

    original = module.run_tradable_benchmark
    def fail(data,spec,research,*args,**kwargs):
        if research.min_commission == 50:
            raise ValueError("injected scenario failure")
        return original(data,spec,research,*args,**kwargs)
    monkeypatch.setattr(module,"run_tradable_benchmark",fail)
    with pytest.raises(ValueError,match="sensitivity scenarios failed"):
        _run(directory,protocol,frozen,tmp_path)
    with ExperimentRegistry(tmp_path/"registry.sqlite") as registry:
        experiment = registry.experiments()[0]
        failed = registry.attempts(experiment.experiment_id)[0]
    assert failed.status == "failed" and failed.result_fingerprint and failed.report_path
    report = Path(failed.report_path)
    assert verify_odd_lot_study_report(report)
    payload = json.loads((report/"matched_sensitivity.json").read_text())
    assert sum(row["status"] == "failed" for row in payload["outcomes"]) == 1
    assert sum(row["status"] == "succeeded" for row in payload["outcomes"]) == len(payload["outcomes"])-1
    before = {path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in report.iterdir()}
    monkeypatch.setattr(module,"run_tradable_benchmark",original)
    retry = _run(directory,protocol,frozen,tmp_path)
    assert retry.attempt.status == "succeeded" and retry.attempt.attempt == 2
    assert all(hashlib.sha256((report/name).read_bytes()).hexdigest() == digest for name,digest in before.items())


def test_rehashed_scenario_settings_and_summary_cannot_change_assumptions(tmp_path, monkeypatch):
    directory, protocol, benchmark, frozen = _v4(tmp_path,monkeypatch,ready=True)
    with pytest.raises(ValueError,match="requires diagnostics"):
        protocol_from_studies((directory,),periods=protocol.periods,selection=protocol.selection,
            execution=protocol.execution,declared_at=protocol.declared_at,
            benchmark_spec=benchmark,matched_sensitivity=True)
    result = _run(directory,protocol,frozen,tmp_path)
    path = next(result.report.glob("scenario_*_account.json"))
    before = path.read_bytes()
    payload = json.loads(path.read_text())
    payload["research"]["commission_bps"] = 0
    path.write_text(canonical_json(payload))
    _rehash(result.report,path)
    assert not verify_odd_lot_study_report(result.report)
    path.write_bytes(before)
    _rehash(result.report,path)
    assert verify_odd_lot_study_report(result.report)
    path = result.report/"sensitivity.csv"
    frame = pd.read_csv(path)
    frame.loc[0,"ending_equity"] = 1e6
    frame.to_csv(path,index=False)
    _rehash(result.report,path)
    assert not verify_odd_lot_study_report(result.report)
