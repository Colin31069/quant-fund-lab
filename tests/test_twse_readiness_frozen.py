"""New official studies bind readiness while legacy archives retain their format."""
import json
from dataclasses import replace

import pandas as pd
import pytest
from test_twse_odd_lot import _bundle

from quant_fund_lab.market_calendar import expected_market_sessions
from quant_fund_lab.odd_lot_study import (
    export_odd_lot_study_report,
    freeze_odd_lot_study,
    load_frozen_odd_lot_study,
    run_frozen_odd_lot_study,
    verify_odd_lot_study_report,
)
from quant_fund_lab.twse_calendar import is_official_closure, official_calendar
from quant_fund_lab.twse_odd_lot import (
    COVERAGE_CATEGORIES,
    import_twse_file,
    prepare_twse_odd_lot,
)
from quant_fund_lab.twse_quality.types import fingerprint


def test_frozen_readiness_blocks_before_performance_and_is_hashed(tmp_path):
    root, symbols = _bundle(tmp_path)
    inputs = prepare_twse_odd_lot(root, symbols, "2025-06-09", "2025-06-20")
    study_root = freeze_odd_lot_study(
        inputs.data, tmp_path / "studies", symbols=tuple(symbols[:2]), benchmark=symbols[2],
        source="twse_official", source_provenance=inputs.provenance,
        source_files=inputs.source_files, source_hashes=inputs.source_hashes,
        quality_issues=[],
    )
    _, metadata = load_frozen_odd_lot_study(study_root)
    assert metadata["schema_version"] == 3
    result = run_frozen_odd_lot_study(study_root)
    assert result.comparison.empty and not result.results
    assert len(result.unavailable) == 12
    assert result.readiness_fingerprint == metadata["readiness_fingerprint"]
    report = export_odd_lot_study_report(study_root, result)
    assert verify_odd_lot_study_report(report)
    assert result.readiness_fingerprint in (report / "report.html").read_text()
    (report / "readiness.json").write_text("{}")
    assert not verify_odd_lot_study_report(report)
    with pytest.raises(ValueError, match="readiness"):
        export_odd_lot_study_report(study_root, replace(result, readiness_fingerprint="wrong"))


def test_effective_calendar_preserves_symbol_suspensions_and_rejects_tampering(tmp_path):
    root, symbols = _bundle(tmp_path)
    inputs = prepare_twse_odd_lot(root, symbols, "2025-06-09", "2025-06-20")
    calendar = official_calendar(inputs, "2025-06-09", "2025-06-20")
    assert calendar is not None
    assert any(str(day.date()) == "2025-06-12" for day in calendar.sessions)
    assert "twse-closures-v1" in calendar.revision
    assert official_calendar(inputs, "2024-01-01", "2025-06-20") is None
    inputs.source_files["suspensions.csv"].write_text("changed")
    with pytest.raises(ValueError, match="integrity"):
        official_calendar(inputs, "2025-06-09", "2025-06-20")


def test_compensatory_holiday_is_a_closure_but_reopening_is_not():
    assert is_official_closure("國定假日", "適逢週末，補假一日")
    assert not is_official_closure("春節後開始交易日", "開始交易")


def test_normalized_data_cannot_disagree_with_frozen_raw_sources(tmp_path):
    root, symbols = _bundle(tmp_path)
    inputs = prepare_twse_odd_lot(root, symbols, "2025-06-09", "2025-06-20")
    raw = inputs.data.raw_open.copy()
    raw.iloc[0, 0] += 1
    with pytest.raises(ValueError, match="normalized data"):
        freeze_odd_lot_study(
            replace(inputs.data, raw_open=raw), tmp_path / "studies",
            symbols=tuple(symbols[:2]), benchmark=symbols[2], source="twse_official",
            source_provenance=inputs.provenance, source_files=inputs.source_files,
            source_hashes=inputs.source_hashes, quality_issues=[],
        )


def test_older_readiness_decision_remains_readable_but_is_not_rerun(tmp_path):
    import hashlib

    root, symbols = _bundle(tmp_path)
    inputs = prepare_twse_odd_lot(root, symbols, "2025-06-09", "2025-06-20")
    frozen = freeze_odd_lot_study(inputs.data, tmp_path / "studies", symbols=tuple(symbols[:2]),
        benchmark=symbols[2], source="twse_official", source_provenance=inputs.provenance,
        source_files=inputs.source_files, source_hashes=inputs.source_hashes, quality_issues=[])
    path = frozen / "study.json"
    metadata = json.loads(path.read_text())
    metadata.pop("study_id")
    metadata["readiness"]["rule_version"] = "readiness-v1"
    for finding in metadata["readiness"]["findings"]:
        finding.pop("blocking")
        finding.pop("applicability_reason")
    metadata["readiness_fingerprint"] = fingerprint(metadata["readiness"])
    canonical = json.dumps(metadata, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode()
    metadata["study_id"] = hashlib.sha256(canonical).hexdigest()[:24]
    path.write_text(json.dumps(metadata))
    assert load_frozen_odd_lot_study(frozen)[1]["readiness"]["rule_version"] == "readiness-v1"
    with pytest.raises(ValueError, match="older readiness"):
        run_frozen_odd_lot_study(frozen)


def _ready_official_bundle(tmp_path, *, start="2024-08-01", end="2025-05-30", sessions=125, price="100"):
    from test_twse_odd_lot import _write_rows

    symbols = ["2330.TW", "2317.TW", "0050.TW"]
    dates = pd.DatetimeIndex(expected_market_sessions("TW", start, end).sessions)[:sessions]
    root = tmp_path / "complete"
    source = tmp_path / "source.json"
    for symbol in symbols:
        for month in dates.to_period("M").unique():
            days = dates[dates.to_period("M") == month]
            source.write_text(json.dumps({"stat": "OK", "title": f"{symbol[:-3]} fixture",
                "date": month.strftime("%Y%m01"), "fields": ["日期", "開盤價", "收盤價", "成交股數"],
                "data": [[str(day.date()), price(day) if callable(price) else price,
                          price(day) if callable(price) else price, "1000000"] for day in days]}))
            import_twse_file(root, source, kind="price", symbol=symbol, month=str(month),
                             source_url="https://www.twse.com.tw/price")
    for year in sorted(set(dates.year)):
        for kind in ("ex_right_index", "etf_split_index", "par_change_index", "reduction_index", "holiday_index"):
            fields = ["日期", "名稱", "說明"] if kind == "holiday_index" else ["資料日期", "股票代號"]
            source.write_text(json.dumps({"stat": "OK", "fields": fields, "data": []}))
            import_twse_file(root, source, kind=kind, year=year,
                             source_url="https://www.twse.com.tw/calendar")
    evidence = root / "evidence" / "review.txt"
    evidence.parent.mkdir()
    evidence.write_text("minimal offline review fixture")
    ref = {"source_url": "https://www.twse.com.tw/review", "evidence_path": "evidence/review.txt"}
    start, end = str(dates[0].date()), str(dates[-1].date())
    _write_rows(root / "coverage_reviews.csv", ["symbol", "start", "end", "category", *ref], [
        {"symbol": symbol, "start": start, "end": end, "category": category, **ref}
        for symbol in symbols for category in COVERAGE_CATEGORIES
    ])
    inputs = prepare_twse_odd_lot(root, symbols, start, end)
    assert not inputs.issues
    return root, symbols, dates, inputs


def test_ready_official_inputs_can_run_and_export_same_decision(tmp_path, monkeypatch):
    import quant_fund_lab.odd_lot_study as module

    _, symbols, dates, inputs = _ready_official_bundle(tmp_path)
    end = str(dates[-1].date())
    monkeypatch.setattr(module, "PERIODS", {"validation": (str(dates[120].date()), end)})
    frozen = freeze_odd_lot_study(
        inputs.data, tmp_path / "studies", symbols=tuple(symbols[:2]), benchmark=symbols[2],
        source="twse_official", source_provenance=inputs.provenance,
        source_files=inputs.source_files, source_hashes=inputs.source_hashes, quality_issues=[],
    )
    _, metadata = load_frozen_odd_lot_study(frozen)
    assert metadata["readiness"]["periods"][0]["status"] == "ready"
    result = run_frozen_odd_lot_study(frozen)
    assert not result.unavailable and len(result.results) == 3
    report = export_odd_lot_study_report(frozen, result)
    assert verify_odd_lot_study_report(report)
