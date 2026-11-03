"""V5 decisions authenticate actual accounts, complete candidate budgets and immutable snapshots."""
import hashlib
import json
import sqlite3
from dataclasses import replace

import pandas as pd
import pytest
from decision_fixtures import decision_fixture, run_candidate
from test_registered_odd_lot_study import SOURCE

from quant_fund_lab.odd_lot_decisions.registry_evidence import collect_decision_inputs
from quant_fund_lab.odd_lot_decisions.workflow import (
    build_registered_decision,
    export_registered_decision,
    verify_registered_decision_report,
)
from quant_fund_lab.odd_lot_protocol import ExperimentRegistry, protocol_from_studies
from quant_fund_lab.odd_lot_protocol.decision import policy_from_plan
from quant_fund_lab.odd_lot_protocol.types import canonical_json
from quant_fund_lab.odd_lot_study import verify_odd_lot_study_report


def _export(tmp_path, frozen):
    return export_registered_decision(frozen,registry_path=tmp_path/"registry.sqlite",
        studies_directory=tmp_path/"studies",output_directory=tmp_path/"decisions",source_directory=SOURCE)


def _verify(tmp_path, report):
    return verify_registered_decision_report(report,registry_path=tmp_path/"registry.sqlite",
                                             studies_directory=tmp_path/"studies")


def _rehash(report, artifact):
    path = report/"report_manifest.json"
    manifest = json.loads(path.read_text())
    manifest.pop("report_id")
    manifest["files"][artifact.name] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest["report_id"] = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    path.write_text(canonical_json(manifest))


def test_policy_is_frozen_and_period_or_selection_mismatch_is_rejected(tmp_path, monkeypatch):
    studies, protocol, frozen, args = decision_fixture(tmp_path,monkeypatch)
    policy = policy_from_plan(protocol.analysis_plan_json)
    assert policy.development_objective == "annual_return"
    assert policy_from_plan(json.dumps({"engine":"frozen_odd_lot_batch_v4",
        "automatic_candidate_selection":False},sort_keys=True,separators=(",",":"))) is None
    changed = protocol_from_studies(studies,**args,decision_policy=replace(policy,maximum_validation_drawdown=.5))
    assert changed.protocol_id != protocol.protocol_id
    for overrides in ({"matched_sensitivity":False},
        {"periods":tuple(replace(row,purpose="historical_exploration") if row.name == "development" else row for row in protocol.periods)},
        {"selection":replace(protocol.selection,development_objective="calmar")}):
        with pytest.raises(ValueError):
            protocol_from_studies(studies,**{**args,**overrides},decision_policy=policy)
    result, inputs = build_registered_decision(frozen,registry_path=tmp_path/"registry.sqlite",studies_directory=tmp_path/"studies")
    assert result.status == "incomplete_search" and result.selected_candidate is None
    assert len(inputs.sources) == 1 and inputs.sources[0].experiment is None


def test_ready_report_derives_no_trade_sample_and_rejects_rehashed_decision(tmp_path, monkeypatch):
    _, protocol, frozen, _ = decision_fixture(tmp_path,monkeypatch)
    run_candidate(tmp_path,protocol,frozen)
    first = _export(tmp_path,frozen)
    second = _export(tmp_path,frozen)
    assert first.decision.status == "insufficient_sample"
    assert first.decision.decision_id == second.decision.decision_id and first.report != second.report
    assert _verify(tmp_path,first.report)
    evidence = json.loads((first.report/"evidence.json").read_text())
    assert all(row["development"]["completed_episodes"] == 0 for row in evidence)
    assert "沒有外部簽章" in (first.report/"report.html").read_text()
    path = first.report/"decision.json"
    raw = json.loads(path.read_text())
    raw["status"] = "continue"
    path.write_text(canonical_json(raw))
    _rehash(first.report,path)
    assert not _verify(tmp_path,first.report)


def test_actual_complete_candidate_grid_can_continue_and_preserves_prior_snapshots(tmp_path, monkeypatch):
    _, protocol, frozen, _ = decision_fixture(tmp_path,monkeypatch,positive=True,count=2)
    first = run_candidate(tmp_path,protocol,frozen)
    partial = _export(tmp_path,frozen)
    assert partial.decision.status == "incomplete_search"
    assert partial.decision.selected_candidate is None
    run_candidate(tmp_path,protocol,frozen,protocol.candidates[1].candidate_id)
    complete = _export(tmp_path,frozen)
    assert complete.decision.status == "continue"
    assert complete.decision.selected_candidate == min(row.candidate_id for row in protocol.candidates)
    assert _verify(tmp_path,partial.report) and _verify(tmp_path,complete.report)
    evidence = json.loads((complete.report/"evidence.json").read_text())
    assert all(row["development"]["completed_episodes"] >= 30 for row in evidence)
    assert all(row["validation"]["completed_episodes"] >= 30 for row in evidence)
    with ExperimentRegistry(tmp_path/"registry.sqlite") as registry:
        pending = registry.start_attempt(first.experiment.experiment_id)
    running = _export(tmp_path,frozen)
    assert running.decision.status == "incomplete_search" and running.decision.selected_candidate is None
    with ExperimentRegistry(tmp_path/"registry.sqlite") as registry:
        registry.finish_attempt(first.experiment.experiment_id,pending.attempt,status="failed",reason="injected later failure")
    current = _export(tmp_path,frozen)
    assert current.decision.status == "incomplete_search"
    assert _verify(tmp_path,complete.report) and _verify(tmp_path,running.report)
    assert "injected later failure" in (current.report/"report.html").read_text()


@pytest.mark.parametrize("artifact",["comparison","account_settings","attempt"])
def test_report_or_registry_binding_tampering_cannot_supply_evidence(tmp_path, monkeypatch, artifact):
    _, protocol, frozen, _ = decision_fixture(tmp_path,monkeypatch)
    run = run_candidate(tmp_path,protocol,frozen)
    report = run.report
    if artifact == "comparison":
        path = report/"comparison.csv"
        frame = pd.read_csv(path)
        frame.loc[frame.strategy.eq("ensemble"),"annual_return"] = 999
        frame.to_csv(path,index=False)
    elif artifact == "account_settings":
        path = report/"study_ledger.sqlite"
        with sqlite3.connect(path) as connection:
            connection.execute("DROP TRIGGER no_account_update")
            connection.execute("UPDATE accounts SET settings_json='{}' WHERE account_id='development/ensemble'")
    else:
        path = report/"experiment.json"
        context = json.loads(path.read_text())
        context["attempt"] = 999
        path.write_text(canonical_json(context))
    _rehash(report,path)
    # Base report hashes can be rewritten; the decision adapter must verify the source semantics.
    if artifact != "attempt":
        assert verify_odd_lot_study_report(report)
    with pytest.raises(ValueError):
        collect_decision_inputs(frozen,registry_path=tmp_path/"registry.sqlite",studies_directory=tmp_path/"studies")


def test_source_directory_mismatch_cannot_publish_a_decision(tmp_path, monkeypatch):
    _, _, frozen, _ = decision_fixture(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match="executing package"):
        export_registered_decision(frozen,registry_path=tmp_path/"registry.sqlite",studies_directory=tmp_path/"studies",
            output_directory=tmp_path/"decisions",source_directory=tmp_path)


def test_failed_required_etf_scenario_blocks_decision_until_successful_retry(tmp_path, monkeypatch):
    from quant_fund_lab.odd_lot_sensitivity import engine

    _, protocol, frozen, _ = decision_fixture(tmp_path,monkeypatch,positive=True)
    original = engine.run_tradable_benchmark
    def fail(data,spec,research,*args,**kwargs):
        if research.min_commission == 50:
            raise ValueError("injected required ETF counterpart failure")
        return original(data,spec,research,*args,**kwargs)
    monkeypatch.setattr(engine,"run_tradable_benchmark",fail)
    with pytest.raises(ValueError,match="sensitivity scenarios failed"):
        run_candidate(tmp_path,protocol,frozen)
    decision, inputs = build_registered_decision(frozen,registry_path=tmp_path/"registry.sqlite",
                                                studies_directory=tmp_path/"studies")
    assert decision.status == "unavailable" and decision.selected_candidate is not None
    assert any("counterpart unavailable" in reason for reason in decision.reasons)
    assert all(row.development.completed_episodes >= 30 for row in inputs.evidence)
    assert inputs.sources[0].attempts[-1].status == "failed"
    monkeypatch.setattr(engine,"run_tradable_benchmark",original)
    run_candidate(tmp_path,protocol,frozen)
    retried, inputs = build_registered_decision(frozen,registry_path=tmp_path/"registry.sqlite",
                                               studies_directory=tmp_path/"studies")
    assert retried.status == "continue"
    assert [attempt.status for attempt in inputs.sources[0].attempts] == ["failed","succeeded"]
