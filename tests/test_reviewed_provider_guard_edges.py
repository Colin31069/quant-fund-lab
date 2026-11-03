"""Real provider selections cannot bypass benchmark, warmup or unsupported-event gates."""
import hashlib
import json
from dataclasses import asdict, replace

import pandas as pd
import pytest
from test_odd_lot_price_inputs import bundle as bundle  # noqa: PLC0414 -- fixture re-export
from test_reviewed_odd_lot_inputs import _ready_provider_selection

from quant_fund_lab.odd_lot_inputs.prepare import prepare_reviewed_odd_lot_input
from quant_fund_lab.odd_lot_study import (
    export_odd_lot_study_report,
    freeze_odd_lot_study,
    load_frozen_odd_lot_study,
    run_frozen_odd_lot_study,
    verify_odd_lot_study_report,
)
from quant_fund_lab.twse_quality.types import FindingCode


def _damage_official_source(root, symbols, dates, case, *, fault_index=121):
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["sources"]:
        path = root / entry["path"]
        value = json.loads(path.read_text())
        if (case == "unsupported_event" and entry["kind"] == "reduction_index"
                and entry["year"] == dates[fault_index].year):
            value["data"] = [[str(dates[fault_index].date()), symbols[0].removesuffix(".TW")]]
        elif entry["kind"] == "price":
            day = dates[50] if case == "warmup" else dates[fault_index]
            if case == "warmup" or (case == "benchmark" and entry["symbol"] == symbols[2]):
                value["data"] = [row for row in value["data"] if pd.Timestamp(row[0]) != day]
        else:
            continue
        path.write_text(json.dumps(value))
        entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("case", ["benchmark", "warmup", "unsupported_event"])
def test_reviewed_provider_blocks_before_performance_for_every_required_gate(
    tmp_path, bundle, monkeypatch, version, case
):
    import quant_fund_lab.odd_lot_study as module

    root, symbols, dates, original = _ready_provider_selection(tmp_path, bundle)
    policy = replace(original.selection.policy, schema_version=version,
                     policy_id=f"reviewed_provider_v{version}")
    period = {"validation": (str(dates[120].date()), str(dates[-1].date()))}
    ready = prepare_reviewed_odd_lot_input(root, bundle, symbols, policy)
    assert ready.assess(period).periods[0].status == "ready"
    _damage_official_source(root, symbols, dates, case)
    before = {p: p.read_bytes() for directory in (root, bundle) for p in directory.rglob("*") if p.is_file()}
    prepared = prepare_reviewed_odd_lot_input(root, bundle, symbols, policy)
    assert sum(row.source.provider == "FinMind" for row in prepared.selection.selected) == 2
    assessment = prepared.assess(period)
    assert assessment.periods[0].status == "blocked"
    blocking_ids = set(assessment.periods[0].blocking_ids)
    blockers = [finding for finding in assessment.findings if finding.finding_id in blocking_ids]
    if case == "benchmark":
        assert any(f.symbol == symbols[2] and f.code == FindingCode.MISSING_SESSION for f in blockers)
    elif case == "warmup":
        assert len(assessment.periods[0].warmup.verified_sessions) == 119
    else:
        assert any(f.code == FindingCode.UNSUPPORTED_EVENT for f in blockers)
    monkeypatch.setattr(module, "PERIODS", period)
    inputs = prepared.evidence
    frozen = freeze_odd_lot_study(inputs.data, tmp_path / "studies", symbols=tuple(symbols[:2]),
        benchmark=symbols[2], source="provider_reviewed", source_provenance=inputs.provenance,
        source_files=inputs.source_files, source_hashes=inputs.source_hashes,
        quality_issues=[asdict(issue) for issue in inputs.issues])
    _, metadata = load_frozen_odd_lot_study(frozen)
    assert metadata["readiness_fingerprint"] == assessment.readiness_fingerprint

    def forbidden(*_args, **_kwargs):
        pytest.fail("blocked provider input reached performance computation")

    monkeypatch.setattr(module, "run_odd_lot_research", forbidden)
    result = run_frozen_odd_lot_study(frozen)
    assert result.readiness_fingerprint == assessment.readiness_fingerprint
    assert not result.results and result.comparison.empty and set(result.unavailable) == {
        f"validation/{strategy}" for strategy in ("ensemble", "momentum", "equal_weight", "benchmark")}
    report = export_odd_lot_study_report(frozen, result)
    assert verify_odd_lot_study_report(report)
    assert json.loads((report / "readiness.json").read_text()) == json.loads(json.dumps(assessment.to_dict()))
    assert all(p.read_bytes() == content for p, content in before.items())


@pytest.mark.parametrize("version", [1, 2])
def test_only_ready_period_produces_results_after_provider_handoff(tmp_path, bundle, monkeypatch, version):
    import quant_fund_lab.odd_lot_study as module

    root, symbols, dates, original = _ready_provider_selection(tmp_path, bundle)
    policy = replace(original.selection.policy, schema_version=version,
                     policy_id=f"reviewed_provider_v{version}")
    periods = {"development": (str(dates[120].date()), str(dates[121].date())),
               "validation": (str(dates[122].date()), str(dates[-1].date()))}
    _damage_official_source(root, symbols, dates, "benchmark", fault_index=122)
    before = {p: p.read_bytes() for directory in (root, bundle) for p in directory.rglob("*") if p.is_file()}
    prepared = prepare_reviewed_odd_lot_input(root, bundle, symbols, policy)
    assert sum(row.source.provider == "FinMind" for row in prepared.selection.selected) == 2
    assessment = prepared.assess(periods)
    assert {p.period: p.status.value for p in assessment.periods} == {
        "development": "ready", "validation": "blocked"}
    monkeypatch.setattr(module, "PERIODS", periods)
    inputs = prepared.evidence
    frozen = freeze_odd_lot_study(inputs.data, tmp_path / "studies", symbols=tuple(symbols[:2]),
        benchmark=symbols[2], source="provider_reviewed", source_provenance=inputs.provenance,
        source_files=inputs.source_files, source_hashes=inputs.source_hashes,
        quality_issues=[asdict(issue) for issue in inputs.issues])
    result = run_frozen_odd_lot_study(frozen)
    assert result.readiness_fingerprint == assessment.readiness_fingerprint
    assert set(result.results) == {("development", s) for s in ("ensemble", "momentum", "equal_weight")}
    assert set(result.unavailable) == {f"validation/{s}" for s in (
        "ensemble", "momentum", "equal_weight", "benchmark")}
    assert set(result.comparison.period) == {"development"}
    report = export_odd_lot_study_report(frozen, result)
    assert verify_odd_lot_study_report(report)
    assert not list(report.glob("validation_*_equity_curve.csv"))
    assert json.loads((report / "readiness.json").read_text()) == json.loads(json.dumps(assessment.to_dict()))
    assert all(p.read_bytes() == content for p, content in before.items())


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("tamper", ["event_bytes", "selection_rehashed", "selection_removed"])
def test_provider_archives_reject_changed_event_or_rehashed_selection(
    tmp_path, bundle, monkeypatch, version, tamper
):
    import quant_fund_lab.odd_lot_study as module
    from quant_fund_lab.odd_lot_protocol.types import canonical_json

    root, symbols, dates, original = _ready_provider_selection(tmp_path, bundle)
    policy = replace(original.selection.policy, schema_version=version,
                     policy_id=f"reviewed_provider_v{version}")
    _damage_official_source(root, symbols, dates, "benchmark")
    inputs = prepare_reviewed_odd_lot_input(root, bundle, symbols, policy).evidence
    monkeypatch.setattr(module, "PERIODS", {
        "validation": (str(dates[120].date()), str(dates[-1].date()))})
    frozen = freeze_odd_lot_study(inputs.data, tmp_path / "studies", symbols=tuple(symbols[:2]),
        benchmark=symbols[2], source="provider_reviewed", source_provenance=inputs.provenance,
        source_files=inputs.source_files, source_hashes=inputs.source_hashes,
        quality_issues=[asdict(issue) for issue in inputs.issues])
    report = export_odd_lot_study_report(frozen, run_frozen_odd_lot_study(frozen))
    assert verify_odd_lot_study_report(report)
    before = {p: p.read_bytes() for directory in (root, bundle) for p in directory.rglob("*") if p.is_file()}
    if tamper == "event_bytes":
        evidence = frozen / "sources/evidence/review.txt"
        evidence.write_bytes(evidence.read_bytes() + b" changed")
        with pytest.raises(ValueError, match="source.*integrity|source.*hash|source.*changed"):
            load_frozen_odd_lot_study(frozen)
    else:
        selection = report / "price_selection.csv"
        original_bytes = selection.read_text()
        assert "FinMind" in original_bytes
        manifest_path = report / "report_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest.pop("report_id")
        if tamper == "selection_rehashed":
            selection.write_text(original_bytes.replace("FinMind", "TWSE"))
            manifest["files"][selection.name] = hashlib.sha256(selection.read_bytes()).hexdigest()
            assert hashlib.sha256(selection.read_bytes()).hexdigest() == manifest["files"][selection.name]
        else:
            selection.unlink()
            manifest["files"].pop(selection.name)
        manifest["report_id"] = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
        manifest_path.write_text(canonical_json(manifest))
    assert not verify_odd_lot_study_report(report)
    assert all(p.read_bytes() == content for p, content in before.items())
