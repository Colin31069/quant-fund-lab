"""Actual v6 report adapters reject foreign context and rehashed required-source edits."""
import hashlib
import json
import sqlite3
from dataclasses import replace

import pandas as pd
import pytest
from decision_fixtures import run_candidate
from phased_fixtures import phased_fixture

from quant_fund_lab.odd_lot_decisions.report_evidence import (
    checked_report,
    report_candidate_evidence,
)
from quant_fund_lab.odd_lot_protocol.benchmark import benchmark_from_plan
from quant_fund_lab.odd_lot_protocol.types import canonical_json
from quant_fund_lab.odd_lot_study import verify_odd_lot_study_report
from quant_fund_lab.twse_quality.types import fingerprint


def _rehash(report, path):
    manifest_path = report / "report_manifest.json"
    value = json.loads(manifest_path.read_text())
    value.pop("report_id")
    value["files"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    value["report_id"] = fingerprint(value)
    manifest_path.write_text(canonical_json(value))
    assert value["files"][path.name] == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("case", ["foreign_protocol", "sessions", "benchmark_settings",
                                  "scenario_deleted", "policy", "diagnostic"])
def test_actual_v6_required_report_sources_reject_rehashed_or_foreign_inputs(tmp_path, monkeypatch, case):
    _, protocol, frozen, _, _ = phased_fixture(tmp_path, monkeypatch)
    run = run_candidate(tmp_path, protocol, frozen)
    studies = tmp_path / "studies"
    assert checked_report(run.report, studies, protocol, run.experiment, run.attempt)
    evidence = report_candidate_evidence(run.report, studies, protocol, run.experiment, run.attempt)
    assert len(evidence) == 2 and all(row.validation.status == "available" for row in evidence)
    assert all(row.validation.completed_episodes == 0 for row in evidence)
    protected = {p: p.read_bytes() for directory in (frozen, studies / run.experiment.study_id / "sources")
                 for p in directory.rglob("*") if p.is_file()}
    registry = tmp_path / "registry.sqlite"
    registry_bytes = registry.read_bytes()
    if case == "foreign_protocol":
        with pytest.raises(ValueError, match="verification"):
            checked_report(run.report, studies, replace(protocol, seed=protocol.seed + 1),
                           run.experiment, run.attempt)
    elif case == "sessions":
        path = run.report / "validation_ensemble_equity_curve.csv"
        frame = pd.read_csv(path)
        frame.iloc[0, 0] = (pd.Timestamp(frame.iloc[0, 0]) - pd.Timedelta(days=1)).date().isoformat()
        frame.to_csv(path, index=False)
        _rehash(run.report, path)
        with pytest.raises(ValueError, match="sessions differ"):
            report_candidate_evidence(run.report, studies, protocol, run.experiment, run.attempt)
    elif case == "benchmark_settings":
        path = run.report / "study_ledger.sqlite"
        with sqlite3.connect(path) as db:
            db.execute("DROP TRIGGER no_account_update")
            benchmark = benchmark_from_plan(protocol.analysis_plan_json)
            row = db.execute("SELECT account_id,settings_json FROM accounts WHERE account_id=?",
                             (f"validation/{benchmark.result_name}",)).fetchone()
            assert row is not None
            settings = json.loads(row[1])
            settings["research"]["instrument_rules"][protocol.benchmark]["sell_tax_bps"] = 99
            changed = canonical_json(settings)
            db.execute("UPDATE accounts SET settings_json=?,settings_sha256=? WHERE account_id=?",
                       (changed, hashlib.sha256(changed.encode()).hexdigest(), row[0]))
        _rehash(run.report, path)
        with pytest.raises(ValueError, match="settings differ"):
            report_candidate_evidence(run.report, studies, protocol, run.experiment, run.attempt)
    else:
        name = {"scenario_deleted": "matched_sensitivity.json", "policy": "protocol.json",
                "diagnostic": "risk_diagnostics.json"}[case]
        path = run.report / name
        value = json.loads(path.read_text())
        if case == "scenario_deleted":
            value["outcomes"].pop()
        elif case == "policy":
            plan = json.loads(value["protocol"]["analysis_plan_json"])
            plan["decision_policy"]["minimum_validation_annual_return"] = .01
            value["protocol"]["analysis_plan_json"] = canonical_json(plan)
            value["protocol_id"] = fingerprint(value["protocol"])
        else:
            value["accounts"][0]["capital"][0]["available_cash_fraction"] = .123
        path.write_text(canonical_json(value))
        _rehash(run.report, path)
        assert not verify_odd_lot_study_report(run.report)
        with pytest.raises(ValueError, match="verification"):
            checked_report(run.report, studies, protocol, run.experiment, run.attempt)
    assert all(p.read_bytes() == content for p, content in protected.items())
    assert registry.read_bytes() == registry_bytes
