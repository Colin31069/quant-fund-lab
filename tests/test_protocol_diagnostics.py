"""Versioned risk reports reproduce and reconcile with archived account evidence."""
import hashlib
import json

import pytest
from test_protocol_benchmarks import _v2
from test_registered_odd_lot_study import SOURCE

from quant_fund_lab.odd_lot_protocol import (
    ExperimentRegistry,
    freeze_protocol,
    protocol_from_studies,
    run_registered_study,
)
from quant_fund_lab.odd_lot_protocol.diagnostics import diagnostics_enabled
from quant_fund_lab.odd_lot_protocol.types import canonical_json
from quant_fund_lab.odd_lot_study import verify_odd_lot_study_report


def _v3(tmp_path, monkeypatch, *, ready):
    directory, parent, benchmark, _ = _v2(tmp_path, monkeypatch, ready=ready)
    protocol = protocol_from_studies((directory,), periods=parent.periods, selection=parent.selection,
        execution=parent.execution, declared_at=parent.declared_at, parent_protocol_id=parent.protocol_id,
        benchmark_spec=benchmark, risk_diagnostics=True)
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        registry.register_protocol(parent)
    assert not diagnostics_enabled(parent.analysis_plan_json)
    assert diagnostics_enabled(protocol.analysis_plan_json)
    return directory, protocol, freeze_protocol(protocol, tmp_path / "protocols")


def _run(directory, protocol, frozen, tmp_path):
    return run_registered_study(frozen, protocol.candidates[0].candidate_id,
        studies_directory=directory.parent, registry_path=tmp_path / "registry.sqlite", source_directory=SOURCE)


def _rehash(report, artifact):
    path = report / "report_manifest.json"
    manifest = json.loads(path.read_text())
    manifest.pop("report_id")
    manifest["files"][artifact.name] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest["report_id"] = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    path.write_text(canonical_json(manifest))


def test_ready_v3_reproduces_and_exports_source_reconciled_diagnostics(tmp_path, monkeypatch):
    directory, protocol, frozen = _v3(tmp_path, monkeypatch, ready=True)
    first = _run(directory, protocol, frozen, tmp_path)
    second = _run(directory, protocol, frozen, tmp_path)
    assert first.attempt.status == second.attempt.status == "succeeded"
    assert first.attempt.result_fingerprint == second.attempt.result_fingerprint
    assert verify_odd_lot_study_report(first.report)
    payload = json.loads((first.report / "risk_diagnostics.json").read_text())
    assert len(payload["accounts"]) == 4 * len(protocol.periods) and not payload["unavailable"]
    assert payload["rule_version"] == "odd_lot_risk_diagnostics_v1"
    assert "風險診斷" in (first.report / "report.html").read_text()
    for account in payload["accounts"]:
        prefix = account["period"] + "_" + account["strategy"]
        assert (first.report / f"{prefix}_episode_risk_audit.csv").exists()
        assert (first.report / f"{prefix}_capital_utilization.csv").exists()
        assert (first.report / f"{prefix}_unfilled_order_summary.csv").exists()
    path = first.report / "risk_diagnostics.json"
    payload["accounts"][0]["capital"][0]["available_cash_fraction"] = .123
    path.write_text(canonical_json(payload))
    _rehash(first.report, path)
    assert not verify_odd_lot_study_report(first.report)


def test_blocked_v3_has_no_invented_accounts_or_sample_statistics(tmp_path, monkeypatch):
    directory, protocol, frozen = _v3(tmp_path, monkeypatch, ready=False)
    result = _run(directory, protocol, frozen, tmp_path)
    assert result.attempt.status == "blocked" and verify_odd_lot_study_report(result.report)
    payload = json.loads((result.report / "risk_diagnostics.json").read_text())
    assert payload["accounts"] == [] and len(payload["unavailable"]) == 15
    assert not list(result.report.glob("*_capital_utilization.csv"))
    assert "沒有可計算診斷的帳戶" in (result.report / "report.html").read_text()


def test_diagnostic_csv_rehash_does_not_bypass_reconstruction(tmp_path, monkeypatch):
    directory, protocol, frozen = _v3(tmp_path, monkeypatch, ready=True)
    result = _run(directory, protocol, frozen, tmp_path)
    path = next(result.report.glob("*_capital_utilization.csv"))
    path.write_text(path.read_text().replace("available", "tampered", 1))
    _rehash(result.report, path)
    assert not verify_odd_lot_study_report(result.report)
    with pytest.raises(ValueError, match="explicit benchmark"):
        protocol_from_studies((directory,), periods=protocol.periods, selection=protocol.selection,
            execution=protocol.execution, declared_at=protocol.declared_at, risk_diagnostics=True)
