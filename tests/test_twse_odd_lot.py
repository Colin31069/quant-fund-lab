import csv
import hashlib
import json
from dataclasses import fields, replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.odd_lot_research import OddLotResearchConfig, run_odd_lot_research
from quant_fund_lab.odd_lot_study import (
    export_odd_lot_study_report,
    freeze_odd_lot_study,
    load_frozen_odd_lot_study,
    run_frozen_odd_lot_study,
    verify_odd_lot_study_report,
)
from quant_fund_lab.twse_odd_lot import (
    COVERAGE_CATEGORIES,
    _total_return,
    download_twse_bundle,
    import_twse_file,
    populate_cash_dividends,
    prepare_twse_odd_lot,
)


def _write_rows(path, fields_, rows):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields_)
        writer.writeheader()
        writer.writerows(rows)


def _bundle(tmp_path):
    root = tmp_path / "bundle"
    symbols = ["2330.TW", "2881.TW", "0050.TW"]
    dates = pd.bdate_range("2025-06-09", "2025-06-20")
    suspended = pd.bdate_range("2025-06-11", "2025-06-17")
    price_fields = ["日期", "成交股數", "開盤價", "收盤價"]
    for symbol in symbols:
        rows = []
        for date in dates:
            if symbol == "0050.TW" and date in suspended:
                continue
            if symbol == "0050.TW":
                close = 188.65 if date < pd.Timestamp("2025-06-18") else 47.57
            elif symbol == "2881.TW":
                close = 100 if date < pd.Timestamp("2025-06-18") else 89.09
            else:
                close = 100
            roc_date = f"{date.year - 1911:03d}/{date.month:02d}/{date.day:02d}"
            rows.append([roc_date, "1,000,000", str(close), str(close)])
        source = tmp_path / f"{symbol}.json"
        source.write_text(json.dumps({"stat": "OK", "title": f"114年06月 {symbol[:-3]} 各日成交資訊", "date": "20250601", "fields": price_fields, "data": rows}), encoding="utf-8")
        import_twse_file(root, source, kind="price", symbol=symbol, month="2025-06",
                         source_url="https://www.twse.com.tw/price")
    source = tmp_path / "events.json"
    source.write_text(json.dumps({"stat": "OK", "fields": ["資料日期", "股票代號"],
                                  "data": [["114年06月18日", "2881"]]}), encoding="utf-8")
    import_twse_file(root, source, kind="ex_right_index", year=2025,
                     source_url="https://www.twse.com.tw/events")
    for kind, symbol_field in (("etf_split_index", "ETF代號"),
                               ("par_change_index", "股票代號"),
                               ("reduction_index", "股票代號")):
        source = tmp_path / f"{kind}.json"
        source.write_text(json.dumps({"stat": "OK", "fields": ["恢復買賣日期", symbol_field], "data": []}), encoding="utf-8")
        import_twse_file(root, source, kind=kind, year=2025, source_url="https://www.twse.com.tw/events")
    holiday = tmp_path / "holiday.json"
    holiday.write_text(json.dumps({"stat": "OK", "fields": ["日期", "名稱", "說明"], "data": []}), encoding="utf-8")
    import_twse_file(root, holiday, kind="holiday_index", year=2025, source_url="https://www.twse.com.tw/calendar")
    evidence = root / "evidence" / "official.txt"
    evidence.parent.mkdir()
    evidence.write_text("official evidence fixture", encoding="utf-8")
    ref = {"source_url": "https://www.twse.com.tw/announcement", "evidence_path": "evidence/official.txt"}
    _write_rows(root / "actions.csv", ["date", "symbol", "split_ratio", "cash_dividend", *ref], [
        {"date": "2025-06-18", "symbol": "2881.TW", "split_ratio": 1.1, "cash_dividend": 2, **ref},
        {"date": "2025-06-18", "symbol": "0050.TW", "split_ratio": 4, "cash_dividend": 0, **ref},
    ])
    _write_rows(root / "suspensions.csv", ["date", "symbol", *ref], [
        {"date": str(date.date()), "symbol": "0050.TW", **ref} for date in suspended
    ])
    _write_rows(root / "coverage.csv", ["symbol", "start", "end", *ref], [
        {"symbol": symbol, "start": "2025-06-09", "end": "2025-06-20", **ref} for symbol in symbols
    ])
    _write_rows(root / "coverage_reviews.csv", ["symbol", "start", "end", "category", *ref], [
        {"symbol": symbol, "start": "2025-06-09", "end": "2025-06-20", "category": category, **ref}
        for symbol in symbols for category in COVERAGE_CATEGORIES
    ])
    return root, symbols


def test_download_records_sources_and_reuses_verified_cache(tmp_path, monkeypatch):
    class Response:
        def __init__(self, url):
            self.url = url

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"stat": "ok", "fields": [], "data": [], "queryYear": 2025}).encode()

    calls = []
    def fake_open(request, timeout):
        calls.append(request.full_url)
        return Response(request.full_url)

    monkeypatch.setattr("quant_fund_lab.twse_odd_lot.urlopen", fake_open)
    root = tmp_path / "download"
    with pytest.raises(PermissionError, match="證交所"):
        download_twse_bundle(root, ["2330.TW"], "2025-06-01", "2025-06-30", delay=0)
    assert not root.exists()
    manifest_path = download_twse_bundle(root, ["2330.TW"], "2025-06-01", "2025-06-30", authorized=True, delay=0)
    manifest = json.loads(manifest_path.read_text())
    assert len(calls) == 6
    assert {entry["kind"] for entry in manifest["sources"]} == {
        "price", "ex_right_index", "etf_split_index", "par_change_index", "reduction_index", "holiday_index"
    }
    assert all(entry["retrieved_at"] and entry["sha256"] for entry in manifest["sources"])
    download_twse_bundle(root, ["2330.TW"], "2025-06-01", "2025-06-30", authorized=True, delay=0)
    assert len(calls) == 6
    for entry in manifest["sources"]:
        entry["retrieved_at"] = "2025-06-01T00:00:00+00:00"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    download_twse_bundle(root, ["2330.TW"], "2025-06-01", "2025-06-30", authorized=True, delay=0)
    assert len(calls) == 12
    updated = json.loads(manifest_path.read_text())
    current_price = next(entry["path"] for entry in updated["sources"] if entry["kind"] == "price")
    assert current_price != "prices/2330_202506.json"
    assert (root / "prices" / "2330_202506.json").exists()
    (root / current_price).write_text("changed")
    with pytest.raises(ValueError, match="雜湊不符"):
        download_twse_bundle(root, ["2330.TW"], "2025-06-01", "2025-06-30", authorized=True, delay=0)


def test_official_bundle_handles_split_distribution_and_suspension(tmp_path):
    root, symbols = _bundle(tmp_path)
    loaded = prepare_twse_odd_lot(root, symbols, "2025-06-09", "2025-06-20")
    assert loaded.issues == ()
    data = loaded.data
    assert data.raw_close.at["2025-06-10", "0050.TW"] == 188.65
    assert pd.isna(data.raw_open.at["2025-06-12", "0050.TW"])
    assert data.volume.at["2025-06-12", "0050.TW"] == 0
    assert data.raw_close.at["2025-06-12", "0050.TW"] == 188.65
    assert data.close.at["2025-06-18", "0050.TW"] / data.close.at["2025-06-10", "0050.TW"] == pytest.approx(47.57 * 4 / 188.65)
    assert data.close.at["2025-06-18", "2881.TW"] / data.close.at["2025-06-17", "2881.TW"] == pytest.approx((89.09 * 1.1 + 2) / 100)
    assert "evidence/official.txt" in loaded.source_hashes


def test_legacy_coverage_does_not_prove_category_review(tmp_path):
    root, symbols = _bundle(tmp_path)
    (root / "coverage_reviews.csv").unlink()
    loaded = prepare_twse_odd_lot(root, symbols, "2025-06-09", "2025-06-20")
    gaps = [issue for issue in loaded.issues if "缺少企業行動覆蓋審核" in issue.detail]
    assert len(gaps) == len(symbols) * len(COVERAGE_CATEGORIES)
    assert "coverage.csv" in loaded.source_hashes
    assert "coverage_reviews.csv" not in loaded.source_hashes
    assert not (root / "coverage_reviews.csv").exists()


def test_one_category_cannot_cover_another(tmp_path):
    root, symbols = _bundle(tmp_path)
    path = root / "coverage_reviews.csv"
    with path.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        rows, columns = list(reader), reader.fieldnames
    _write_rows(path, columns, [r for r in rows if r["symbol"] != "2330.TW" or r["category"] != "reduction"])
    loaded = prepare_twse_odd_lot(root, symbols, "2025-06-09", "2025-06-20")
    gaps = [issue for issue in loaded.issues if "缺少企業行動覆蓋審核" in issue.detail]
    assert len(gaps) == 1
    assert gaps[0].symbol == "2330.TW" and gaps[0].detail.endswith("reduction")
    assert "coverage_reviews.csv" in loaded.source_hashes


def test_missing_official_holiday_index_is_reported(tmp_path):
    root, symbols = _bundle(tmp_path)
    path = root / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["sources"] = [entry for entry in manifest["sources"] if entry["kind"] != "holiday_index"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = prepare_twse_odd_lot(root, symbols, "2025-06-09", "2025-06-20")
    assert any(issue.detail == "缺少該年度官方開休市索引" for issue in loaded.issues)


def test_official_holiday_suppresses_calendar_false_positive(tmp_path):
    root = tmp_path / "calendar"
    price = tmp_path / "price.json"
    price.write_text(json.dumps({"stat": "OK", "title": "111年02月 2330 各日成交資訊", "date": "20220201",
                                 "fields": ["日期", "成交股數", "開盤價", "收盤價"],
                                 "data": [["111/02/07", "1000", "100", "100"]]}), encoding="utf-8")
    import_twse_file(root, price, kind="price", symbol="2330.TW", month="2022-02",
                     source_url="https://www.twse.com.tw/price")
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"stat": "OK", "fields": ["資料日期", "股票代號"], "data": []}), encoding="utf-8")
    import_twse_file(root, event, kind="ex_right_index", year=2022, source_url="https://www.twse.com.tw/events")
    for kind, symbol_field in (("etf_split_index", "ETF代號"),
                               ("par_change_index", "股票代號"),
                               ("reduction_index", "股票代號")):
        source = tmp_path / f"{kind}.json"
        source.write_text(json.dumps({"stat": "OK", "fields": ["恢復買賣日期", symbol_field], "data": []}), encoding="utf-8")
        import_twse_file(root, source, kind=kind, year=2022, source_url="https://www.twse.com.tw/events")
    holiday = tmp_path / "holiday.json"
    holiday.write_text(json.dumps({"stat": "ok", "fields": ["日期", "名稱", "說明"], "data": [
        ["2022-02-04", "農曆春節", "調整放假，1月22日補行上班，但不交易亦不交割。"],
        ["2022-02-07", "農曆春節後開始交易日", "農曆春節後開始交易。"]]}), encoding="utf-8")
    import_twse_file(root, holiday, kind="holiday_index", year=2022, source_url="https://www.twse.com.tw/calendar")
    evidence = root / "evidence" / "calendar.json"
    evidence.parent.mkdir()
    evidence.write_bytes(holiday.read_bytes())
    _write_rows(root / "coverage.csv", ["symbol", "start", "end", "source_url", "evidence_path"], [
        {"symbol": "2330.TW", "start": "2022-02-04", "end": "2022-02-07",
         "source_url": "https://www.twse.com.tw/calendar", "evidence_path": "evidence/calendar.json"}])
    _write_rows(root / "coverage_reviews.csv", ["symbol", "start", "end", "category", "source_url", "evidence_path"], [
        {"symbol": "2330.TW", "start": "2022-02-04", "end": "2022-02-07", "category": category,
         "source_url": "https://www.twse.com.tw/calendar", "evidence_path": "evidence/calendar.json"}
        for category in COVERAGE_CATEGORIES
    ])
    loaded = prepare_twse_odd_lot(root, ["2330.TW"], "2022-02-04", "2022-02-07")
    assert loaded.issues == ()


def test_missing_event_and_suspension_are_reported(tmp_path):
    root, symbols = _bundle(tmp_path)
    _write_rows(root / "actions.csv", ["date", "symbol", "split_ratio", "cash_dividend", "source_url", "evidence_path"], [])
    _write_rows(root / "suspensions.csv", ["date", "symbol", "source_url", "evidence_path"], [])
    loaded = prepare_twse_odd_lot(root, symbols, "2025-06-09", "2025-06-20")
    assert any(issue.symbol == "2881.TW" and "actions.csv" in issue.detail for issue in loaded.issues)
    assert any(issue.symbol == "0050.TW" and "缺少價格" in issue.detail for issue in loaded.issues)
    assert pd.isna(loaded.data.dividends.at["2025-06-18", "2881.TW"])


def test_cash_dividends_can_be_seeded_from_an_official_index(tmp_path):
    root, symbols = _bundle(tmp_path)
    path = root / "events" / "ex_right_index_2025.json"
    data = {
        "stat": "OK",
        "fields": ["資料日期", "股票代號", "權/息", "權值+息值"],
        "data": [["114年06月18日", "2330", "息", "2.500000"],
                 ["114年06月18日", "2881", "權", "5.000000"]],
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["sources"]:
        if entry["path"] == "events/ex_right_index_2025.json":
            entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert populate_cash_dividends(root, symbols) == 1
    assert populate_cash_dividends(root, symbols) == 0
    rows = list(csv.DictReader((root / "actions.csv").open(encoding="utf-8")))
    assert [r["cash_dividend"] for r in rows if r["symbol"] == "2330.TW"] == ["2.5"]
    evidence_files = list((root / "evidence").glob("ex_right_2025_*.json"))
    assert len(evidence_files) == 1 and evidence_files[0].read_bytes() == path.read_bytes()


def test_source_hash_and_duplicate_date_are_rejected(tmp_path):
    root, symbols = _bundle(tmp_path)
    path = root / "prices" / "2330_202506.json"
    raw = json.loads(path.read_text())
    raw["data"].append(raw["data"][0])
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="雜湊不符"):
        prepare_twse_odd_lot(root, symbols, "2025-06-09", "2025-06-20")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["sources"]:
        if entry["path"] == "prices/2330_202506.json":
            entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="重複價格"):
        prepare_twse_odd_lot(root, symbols, "2025-06-09", "2025-06-20")


def test_future_actions_do_not_change_earlier_total_returns(tmp_path):
    root, symbols = _bundle(tmp_path)
    data = prepare_twse_odd_lot(root, symbols, "2025-06-09", "2025-06-20").data
    changed = data.dividends.copy()
    changed.loc["2025-06-19":] = 30
    result = _total_return(data.raw_close, changed, data.stock_splits)
    pd.testing.assert_frame_equal(result.loc[:"2025-06-18"], data.close.loc[:"2025-06-18"])


def test_cash_dividend_uses_pre_split_shares():
    data = synthetic_market_data(("2330.TW", "2317.TW"), periods=70, seed=4)
    dates = data.close.index
    adjusted = pd.DataFrame({"2330.TW": np.linspace(80, 120, 70), "2317.TW": np.linspace(70, 100, 70)}, index=dates)
    raw = adjusted.copy()
    raw.loc[dates[50]:, :] = (raw.loc[dates[50]:, :] - 2) / 2
    splits = adjusted * 0
    dividends = adjusted * 0
    splits.loc[dates[50]] = 2
    dividends.loc[dates[50]] = 2
    data = replace(data, open=adjusted, close=adjusted, raw_open=raw, raw_close=raw,
                   stock_splits=splits, dividends=dividends)
    result = run_odd_lot_research(data, OddLotResearchConfig(strategy="momentum", momentum_lookback=5),
                                  BacktestConfig(initial_cash=100_000, base_currency="TWD",
                                                 strategy=StrategyConfig(warmup_days=30)))
    actions = result.corporate_actions
    cash = actions[actions.action == "cash_dividend"]
    assert not cash.empty
    for event in cash.itertuples():
        split = actions[(actions.action == "stock_split") & (actions.symbol == event.symbol)].iloc[0]
        assert event.quantity_before == split.quantity_before
        assert event.cash_value_local == pytest.approx(event.quantity_before * 2)
    assert not ((result.signals.timestamp == dates[50]) & (result.signals.reason == "stop")).any()


def test_streamlit_exposes_official_source_and_manual_import():
    app_file = Path(__file__).resolve().parents[1] / "src" / "quant_fund_lab" / "ui.py"
    app = AppTest.from_file(str(app_file)).run(timeout=12)
    app = next(c for c in app.checkbox if c.label == "十萬元台股零股策略研究").set_value(True).run(timeout=12)
    assert not app.exception
    assert next(s for s in app.selectbox if s.label == "資料來源").value == "TWSE 官方歷史資料"
    assert any(c.label == "使用已授權的 TWSE 自動下載" and not c.value for c in app.checkbox)
    assert any(b.label == "匯入官方檔案" for b in app.button)
    assert any(b.label == "預覽批次匯入" for b in app.button)
    assert any(b.label == "執行批次匯入" for b in app.button)


def test_quality_gates_periods_and_frozen_sources_are_verified(tmp_path):
    symbols = ("2330.TW", "2317.TW")
    data = synthetic_market_data((*symbols, "0050.TW"), periods=450, seed=7)
    dates = pd.bdate_range("2023-06-01", periods=450)
    frames = {f.name: getattr(data, f.name).set_axis(dates, axis=0) for f in fields(data)
              if isinstance(getattr(data, f.name), pd.DataFrame)}
    data = replace(data, **frames, base_currency="TWD")
    source = tmp_path / "source.txt"
    source.write_text("official fixture", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    issue = {"start": "2024-01-15", "end": "2024-01-15", "symbol": "2330.TW", "detail": "缺少企業行動"}
    root = freeze_odd_lot_study(data, tmp_path / "studies", symbols=symbols,
                                source="synthetic", source_provenance={"coverage_end": str(dates[-1].date())},
                                source_files={"source.txt": source}, source_hashes={"source.txt": digest},
                                quality_issues=[issue])
    # Reconstruct the legacy v2 fixture explicitly; new official freezes use v3.
    metadata_path = root / "study.json"
    metadata = json.loads(metadata_path.read_text())
    metadata.pop("study_id")
    metadata.pop("readiness", None)
    metadata.pop("readiness_fingerprint", None)
    metadata["schema_version"] = 2
    metadata["data_source"] = "twse_official"
    metadata["periods"]["historical_evaluation"][1] = None
    identity = hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(",", ":"),
                                        ensure_ascii=False, allow_nan=False).encode()).hexdigest()[:24]
    metadata_path.write_text(json.dumps({"study_id": identity, **metadata}), encoding="utf-8")
    study = run_frozen_odd_lot_study(root)
    assert "validation/momentum" in study.unavailable
    assert "缺少企業行動" in study.unavailable["validation/momentum"]
    assert ("historical_evaluation", "momentum") in study.results
    report = export_odd_lot_study_report(root, study)
    assert verify_odd_lot_study_report(report)
    manifest = json.loads((report / "report_manifest.json").read_text(encoding="utf-8"))
    assert {"quality_summary.csv", "quality_grouped.csv", "quality_periods.csv", "missing_source_manifest.csv"} <= set(manifest["files"])
    assert load_frozen_odd_lot_study(root)[1]["source_files"]["source.txt"] == digest
    (root / "sources" / "source.txt").write_text("tampered", encoding="utf-8")
    assert not verify_odd_lot_study_report(report)
    with pytest.raises(ValueError, match="source integrity"):
        load_frozen_odd_lot_study(root)


def test_twse_2881_real_report_detects_unmodelled_rights(tmp_path):
    root = tmp_path / "official"
    # Values copied from TWSE STOCK_DAY and TWT49U responses for 2021-09-06.
    prices = tmp_path / "2881.json"
    prices.write_text(json.dumps({"stat": "OK", "date": "20210901", "title": "110年09月 2881 富邦金 各日成交資訊",
                                  "fields": ["日期", "成交股數", "開盤價", "收盤價"],
                                  "data": [["110/09/03", "37,959,062", "83.40", "84.80"],
                                           ["110/09/06", "51,372,524", "77.70", "77.20"]]}), encoding="utf-8")
    import_twse_file(root, prices, kind="price", symbol="2881.TW", month="2021-09",
                     source_url="https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY")
    events = tmp_path / "events.json"
    events.write_text(json.dumps({"stat": "OK", "fields": ["資料日期", "股票代號", "除權息前收盤價", "除權息參考價", "減除股利參考價", "權/息", "權值+息值"],
                                  "data": [["110年09月06日", "2881", "84.80", "76.33", "77.09", "權", "8.464387"]]}), encoding="utf-8")
    import_twse_file(root, events, kind="ex_right_index", year=2021,
                     source_url="https://www.twse.com.tw/rwd/zh/exRight/TWT49U")
    evidence = root / "evidence" / "index.json"
    evidence.parent.mkdir()
    evidence.write_bytes(events.read_bytes())
    ref = {"source_url": "https://www.twse.com.tw/rwd/zh/exRight/TWT49U", "evidence_path": "evidence/index.json"}
    _write_rows(root / "actions.csv", ["date", "symbol", "split_ratio", "cash_dividend", *ref], [
        {"date": "2021-09-06", "symbol": "2881.TW", "split_ratio": 1.1, "cash_dividend": 0, **ref}])
    _write_rows(root / "coverage.csv", ["symbol", "start", "end", *ref], [
        {"symbol": "2881.TW", "start": "2021-09-03", "end": "2021-09-06", **ref}])
    loaded = prepare_twse_odd_lot(root, ["2881.TW"], "2021-09-03", "2021-09-06")
    assert loaded.data.raw_close.at["2021-09-03", "2881.TW"] == 84.80
    assert loaded.data.raw_close.at["2021-09-06", "2881.TW"] == 77.20
    assert any("現金增資" in issue.detail for issue in loaded.issues)
