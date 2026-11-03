"""Acceptance boundaries for read-only assessment, benchmark review and repair."""
import hashlib
import json
import sqlite3
from dataclasses import asdict, replace

import pandas as pd
from streamlit.testing.v1 import AppTest
from test_twse_readiness_frozen import _ready_official_bundle

from quant_fund_lab.odd_lot_study import freeze_odd_lot_study, run_frozen_odd_lot_study
from quant_fund_lab.twse_calendar import official_calendar
from quant_fund_lab.twse_odd_lot import prepare_twse_odd_lot
from quant_fund_lab.twse_preparation import (
    batch_import_twse,
    missing_source_manifest,
    read_batch_manifest,
)
from quant_fund_lab.twse_quality.readiness import assess_study_readiness
from quant_fund_lab.twse_quality.types import FindingCode, ReadinessStatus


def _inventory(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def _assess(root, symbols, dates):
    start, end = str(dates[0].date()), str(dates[-1].date())
    inputs = prepare_twse_odd_lot(root, symbols, start, end)
    periods = {"validation": (str(dates[120].date()), end)}
    result = assess_study_readiness(inputs, periods, calendar=official_calendar(inputs, start, end))
    return inputs, result


def test_repeat_assessment_preserves_all_files_and_existing_database(tmp_path):
    root, symbols, dates, _ = _ready_official_bundle(tmp_path)
    with sqlite3.connect(root / "unrelated.sqlite") as connection:
        connection.execute("CREATE TABLE sentinel(value TEXT)")
        connection.execute("INSERT INTO sentinel VALUES ('preserve')")
    before = _inventory(tmp_path)
    _, first = _assess(root, symbols, dates)
    _, second = _assess(root, symbols, dates)
    assert first.to_dict() == second.to_dict()
    assert first.readiness_fingerprint == second.readiness_fingerprint
    assert first.periods[0].status == ReadinessStatus.READY
    assert _inventory(tmp_path) == before


def test_benchmark_review_gap_blocks_real_runner_with_complete_quotes(tmp_path, monkeypatch):
    import quant_fund_lab.odd_lot_study as module

    root, symbols, dates, _ = _ready_official_bundle(tmp_path)
    path = root / "coverage_reviews.csv"
    reviews = pd.read_csv(path)
    reviews = reviews[~((reviews.symbol == symbols[-1]) & (reviews.category == "split"))]
    reviews.to_csv(path, index=False)
    inputs, decision = _assess(root, symbols, dates)
    assert inputs.data.raw_open.notna().all().all()
    benchmark_findings = [row for row in decision.findings
                          if row.symbol == symbols[-1] and row.code == FindingCode.COVERAGE_REVIEW]
    assert benchmark_findings and decision.periods[0].status == ReadinessStatus.BLOCKED
    assert all(row.finding_id in decision.periods[0].blocking_ids for row in benchmark_findings)
    monkeypatch.setattr(module, "PERIODS", {
        "validation": (str(dates[120].date()), str(dates[-1].date()))})
    frozen = freeze_odd_lot_study(inputs.data, tmp_path / "studies", symbols=tuple(symbols[:2]),
        benchmark=symbols[-1], source="twse_official", source_provenance=inputs.provenance,
        source_files=inputs.source_files, source_hashes=inputs.source_hashes,
        quality_issues=[asdict(issue) for issue in inputs.issues])
    result = run_frozen_odd_lot_study(frozen)
    assert result.readiness_fingerprint == decision.readiness_fingerprint
    assert not result.results and result.comparison.empty
    assert result.unavailable


def test_actual_month_repair_preserves_unmodeled_event_and_coverage_blockers(tmp_path):
    root, symbols, dates, _ = _ready_official_bundle(tmp_path)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    event_day = dates[121]
    event_entry = next(row for row in manifest["sources"]
                       if row["kind"] == "reduction_index" and int(row["year"]) == event_day.year)
    event_path = root / event_entry["path"]
    event_payload = json.loads(event_path.read_text())
    event_payload["data"] = [[str(event_day.date()), symbols[0][:-3]]]
    event_path.write_text(json.dumps(event_payload))
    event_entry["sha256"] = hashlib.sha256(event_path.read_bytes()).hexdigest()
    reviews_path = root / "coverage_reviews.csv"
    reviews = pd.read_csv(reviews_path)
    reviews[~((reviews.symbol == symbols[0]) & (reviews.category == "split"))].to_csv(
        reviews_path, index=False)
    missing = next(row for row in manifest["sources"]
                   if row["kind"] == "price" and row["symbol"] == symbols[0])
    raw = root / missing["path"]
    restored = tmp_path / "restored.json"
    restored.write_bytes(raw.read_bytes())
    raw.unlink()
    manifest["sources"].remove(missing)
    manifest_path.write_text(json.dumps(manifest))
    inputs, before = _assess(root, symbols, dates)
    assert any(row.code == FindingCode.MISSING_MONTH for row in before.findings)
    original_events = {row.finding_id for row in before.findings
                       if row.code == FindingCode.UNSUPPORTED_EVENT}
    assert original_events
    repair = missing_source_manifest(inputs.issues)
    assert len(repair) == 1
    repair["file"] = str(restored)
    repair_file = tmp_path / "repair.csv"
    repair.to_csv(repair_file, index=False)
    assert batch_import_twse(root, read_batch_manifest(repair_file), dry_run=False).status.tolist() == ["imported"]
    _, after = _assess(root, symbols, dates)
    assert after.input_fingerprint != before.input_fingerprint
    assert not any(row.code == FindingCode.MISSING_MONTH for row in after.findings)
    assert original_events == {row.finding_id for row in after.findings
                               if row.code == FindingCode.UNSUPPORTED_EVENT}
    assert original_events.issubset(after.periods[0].blocking_ids)
    assert any(row.code == FindingCode.COVERAGE_REVIEW for row in after.findings)
    assert after.periods[0].status == ReadinessStatus.BLOCKED


def test_display_translation_keeps_assessed_ids_and_blocked_state(tmp_path):
    root, symbols, dates, _ = _ready_official_bundle(tmp_path)
    reviews_path = root / "coverage_reviews.csv"
    reviews = pd.read_csv(reviews_path)
    reviews.iloc[1:].to_csv(reviews_path, index=False)
    _, assessed = _assess(root, symbols, dates)
    translated = replace(assessed, findings=tuple(
        replace(row, detail="Reviewed display translation") for row in assessed.findings))
    before = _inventory(tmp_path)
    ids = [row.finding_id for row in assessed.findings]
    assert ids == [row.finding_id for row in translated.findings]
    assert translated.periods == assessed.periods
    for result in [assessed, translated]:
        script = ("import json, streamlit as st\n"
                  "from quant_fund_lab.twse_quality.ui import render_readiness\n"
                  f"render_readiness(st, json.loads({json.dumps(result.to_dict())!r}), "
                  f"{result.readiness_fingerprint!r})\n")
        app = AppTest.from_string(script).run(timeout=12)
        assert not app.exception
        assert app.dataframe[0].value.iloc[0]["status"] == "blocked"
        assert app.dataframe[0].value.iloc[0]["blocking_count"] == len(assessed.periods[0].blocking_ids)
        assert app.dataframe[1].value.finding_id.tolist() == ids
    assert _inventory(tmp_path) == before
