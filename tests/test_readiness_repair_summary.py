"""Frozen repair summaries distinguish period gaps from dependent warmup gaps."""
import hashlib
import json
from dataclasses import asdict, replace

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from test_twse_readiness_frozen import _ready_official_bundle

from quant_fund_lab.odd_lot_study import (
    export_odd_lot_study_report,
    freeze_odd_lot_study,
    load_frozen_odd_lot_study,
    run_frozen_odd_lot_study,
    verify_odd_lot_study_report,
)
from quant_fund_lab.twse_calendar import official_calendar
from quant_fund_lab.twse_odd_lot import prepare_twse_odd_lot
from quant_fund_lab.twse_quality.readiness import assess_study_readiness
from quant_fund_lab.twse_quality.repairs import (
    REPAIR_SUMMARY_RULE,
    period_repair_summaries,
    repair_summary_frame,
    verify_repair_summary,
)
from quant_fund_lab.twse_quality.types import (
    FindingCode,
    PeriodReadiness,
    ReadinessFinding,
    ReadinessStatus,
    StudyReadiness,
    WarmupEvidence,
    fingerprint,
)


def _freeze(root, symbols, dates, tmp_path, periods, monkeypatch):
    import quant_fund_lab.odd_lot_study as module

    start, end = str(dates[0].date()), str(dates[-1].date())
    inputs = prepare_twse_odd_lot(root, symbols, start, end)
    # The calendar evidence cutoff is part of identity, even with extra source rows.
    cutoff = max(bounds[1] for bounds in periods.values())
    assessed = assess_study_readiness(inputs, periods, calendar=official_calendar(inputs, start, cutoff))
    monkeypatch.setattr(module, "PERIODS", periods)
    frozen = freeze_odd_lot_study(inputs.data, tmp_path / "studies", symbols=tuple(symbols[:2]),
        benchmark=symbols[-1], source="twse_official", source_provenance=inputs.provenance,
        source_files=inputs.source_files, source_hashes=inputs.source_hashes,
        quality_issues=[asdict(issue) for issue in inputs.issues])
    _, metadata = load_frozen_odd_lot_study(frozen)
    assert metadata["readiness_fingerprint"] == assessed.readiness_fingerprint
    assert metadata["readiness"] == json.loads(json.dumps(assessed.to_dict()))
    return frozen, metadata


def _browser(metadata):
    script = ("import json, streamlit as st\n"
              "from quant_fund_lab.twse_quality.ui import render_readiness\n"
              f"render_readiness(st, json.loads({json.dumps(metadata['readiness'])!r}), "
              f"{metadata['readiness_fingerprint']!r})\n")
    app = AppTest.from_string(script).run(timeout=12)
    assert not app.exception
    return app


def _export_checked(frozen, metadata):
    result = run_frozen_odd_lot_study(frozen)
    assert result.readiness_fingerprint == metadata["readiness_fingerprint"]
    report = export_odd_lot_study_report(frozen, result)
    assert verify_odd_lot_study_report(report)
    assert json.loads((report / "readiness.json").read_text()) == metadata["readiness"]
    assert metadata["readiness_fingerprint"] in (report / "report.html").read_text()
    return result, report


def test_cross_period_missing_month_is_separate_from_validation_warmup(tmp_path, monkeypatch):
    root, symbols, dates, _ = _ready_official_bundle(tmp_path, sessions=190)
    month = str(dates[130].to_period("M"))
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    missing = next(row for row in manifest["sources"] if row["kind"] == "price"
                   and row["symbol"] == symbols[0] and row["month"] == month)
    (root / missing["path"]).unlink()
    manifest["sources"].remove(missing)
    manifest_path.write_text(json.dumps(manifest))
    periods = {"development": (str(dates[120].date()), str(dates[149].date())),
               "validation": (str(dates[150].date()), str(dates[180].date()))}
    frozen, metadata = _freeze(root, symbols, dates, tmp_path, periods, monkeypatch)
    rows = {row.period: row for row in period_repair_summaries(metadata["readiness"])}
    assert rows["development"].period_month_keys == ((symbols[0], month),)
    assert rows["validation"].period_month_keys == ()
    assert rows["validation"].warmup_month_keys == ((symbols[0], month),)
    assert rows["validation"].warmup_verified < 120
    assert rows["validation"].warmup_unverified > 0
    result, report = _export_checked(frozen, metadata)
    assert result.comparison.empty and not result.results
    exported = pd.read_csv(report / "readiness_repairs.csv").set_index("period")
    assert exported.loc["development", "period_missing_months"] == 1
    assert exported.loc["validation", "period_missing_months"] == 0
    assert exported.loc["validation", "warmup_missing_months"] == 1
    app = _browser(metadata)
    displayed = next(frame.value for frame in app.dataframe if "period_missing_months" in frame.value.columns)
    pd.testing.assert_frame_equal(displayed, repair_summary_frame(metadata["readiness"]).drop(
        columns=["period_source_keys", "warmup_source_keys"]))
    assert "分期缺月與暖機依賴" in (report / "report.html").read_text()


@pytest.mark.parametrize("blocked", [False, True])
def test_ready_or_blocked_runner_report_and_ui_keep_exact_frozen_decision(tmp_path, monkeypatch, blocked):
    import quant_fund_lab.odd_lot_study as module

    root, symbols, dates, _ = _ready_official_bundle(tmp_path)
    if blocked:
        path = root / "coverage_reviews.csv"
        pd.read_csv(path).iloc[1:].to_csv(path, index=False)
    periods = {"validation": (str(dates[120].date()), str(dates[-1].date()))}
    frozen, metadata = _freeze(root, symbols, dates, tmp_path, periods, monkeypatch)
    if blocked:
        def forbidden(*args, **kwargs):
            raise AssertionError("blocked readiness must not compute account performance")
        monkeypatch.setattr(module, "run_odd_lot_research", forbidden)
    result, report = _export_checked(frozen, metadata)
    assert bool(result.results) != blocked
    before = {str(p.relative_to(frozen)): p.read_bytes() for p in frozen.rglob("*") if p.is_file()}
    app = _browser(metadata)
    periods_table = app.dataframe[0].value
    assert periods_table.iloc[0]["status"] == ("blocked" if blocked else "ready")
    assert periods_table.iloc[0]["blocking_count"] == len(metadata["readiness"]["periods"][0]["blocking_ids"])
    if blocked:
        assert app.dataframe[1].value.finding_id.tolist() == [
            row["finding_id"] for row in metadata["readiness"]["findings"]]
        assert result.comparison.empty and result.unavailable
    app.run(timeout=12)
    assert {str(p.relative_to(frozen)): p.read_bytes() for p in frozen.rglob("*") if p.is_file()} == before
    manifest_path = report / "report_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["repair_summary_rule"] == REPAIR_SUMMARY_RULE
    csv_path = report / "readiness_repairs.csv"
    altered = pd.read_csv(csv_path)
    altered["period_missing_months"] = 99
    altered.to_csv(csv_path, index=False)
    manifest.pop("report_id")
    manifest["files"][csv_path.name] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    manifest["report_id"] = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    assert not verify_odd_lot_study_report(report)


def test_unknown_warmup_is_not_fabricated_and_legacy_report_needs_no_summary(tmp_path):
    readiness = {"findings": [], "periods": [{"period": "validation", "start": "2024-01-01",
        "end": "2024-12-31", "blocking_ids": [],
        "warmup": {"required": 120, "verified_sessions": []}}]}
    row = period_repair_summaries(readiness)[0]
    assert row.warmup_month_keys is None and row.warmup_expected is None
    assert row.warmup_unverified is None and row.to_record()["warmup_missing_months"] is None
    assert verify_repair_summary(tmp_path, {}, {"files": {}})
    assert not verify_repair_summary(tmp_path, {}, {"files": {}, "repair_summary_rule": "unknown"})


def test_shared_month_is_deduplicated_in_each_window_without_counting_context():
    month = ReadinessFinding(FindingCode.MISSING_MONTH, "0050.TW", "2024-01-01", "2024-01-31", "missing")
    repeated = replace(month, discriminator="second source finding")
    context = replace(month, symbol="2330.TW", discriminator="context", blocking=False,
                      applicability_reason="Other source policy; not a necessary price input")
    warmup = WarmupEvidence("reviewed", 120, ("2024-01-02", "2024-01-03"), ())
    period = PeriodReadiness("validation", "2024-01-04", "2024-01-31", ReadinessStatus.BLOCKED,
                             warmup, (month.finding_id, repeated.finding_id))
    decision = StudyReadiness("input", (month, repeated, context), (period,))
    row = period_repair_summaries(decision.to_dict())[0]
    assert row.period_month_keys == (("0050.TW", "2024-01"),)
    assert row.warmup_month_keys == row.period_month_keys
    assert row.to_record()["period_missing_months"] == row.to_record()["warmup_missing_months"] == 1
    assert row.warmup_unverified == 2 and row.to_record()["warmup_shortfall"] == 120


def test_rehashed_new_readiness_cannot_hide_original_blocking_source(tmp_path, monkeypatch):
    root, symbols, dates, _ = _ready_official_bundle(tmp_path)
    path = root / "coverage_reviews.csv"
    pd.read_csv(path).iloc[1:].to_csv(path, index=False)
    periods = {"validation": (str(dates[120].date()), str(dates[-1].date()))}
    frozen, metadata = _freeze(root, symbols, dates, tmp_path, periods, monkeypatch)
    _, report = _export_checked(frozen, metadata)
    metadata["readiness"]["findings"] = []
    metadata["readiness"]["periods"][0]["blocking_ids"] = []
    metadata["readiness"]["periods"][0]["status"] = "ready"
    metadata["readiness_fingerprint"] = fingerprint(metadata["readiness"])
    metadata.pop("study_id")
    metadata["study_id"] = fingerprint(metadata)[:24]
    (frozen / "study.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="frozen readiness differs"):
        load_frozen_odd_lot_study(frozen)
    assert not verify_odd_lot_study_report(report)
