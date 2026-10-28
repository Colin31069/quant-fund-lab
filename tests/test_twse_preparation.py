import csv
import json
from pathlib import Path

import pandas as pd

from quant_fund_lab.twse_odd_lot import TWSEIssue
from quant_fund_lab.twse_preparation import (
    batch_import_twse,
    missing_source_manifest,
    read_batch_manifest,
    summarize_period_issues,
    summarize_quality_issues,
)


def _price(path: Path, symbol: str = "2330", date: str = "20240102") -> dict:
    path.write_text(json.dumps({
        "stat": "OK", "title": f"113年01月 {symbol} 各日成交資訊", "date": "20240101",
        "fields": ["日期", "成交股數", "開盤價", "收盤價"],
        "data": [[f"{date[:4]}-{date[4:6]}-{date[6:]}", "1000", "100", "101"]],
    }), encoding="utf-8")
    return {"file": str(path), "kind": "price", "source_url": "https://www.twse.com.tw/price",
            "symbol": f"{symbol}.TW", "month": "2024-01", "year": ""}


def test_batch_preview_retry_conflict_and_invalid_identity(tmp_path):
    root = tmp_path / "bundle"
    row = _price(tmp_path / "one.json")
    wrong = {**row, "symbol": "2317.TW"}
    preview = batch_import_twse(root, [row, row, wrong])
    assert preview.status.tolist() == ["ready", "duplicate", "error"]
    assert not root.exists()
    result = batch_import_twse(root, [row, row, wrong], dry_run=False)
    assert result.status.tolist() == ["imported", "present", "error"]
    assert len(json.loads((root / "manifest.json").read_text())["sources"]) == 1
    assert batch_import_twse(root, [row], dry_run=False).status.tolist() == ["present"]
    changed = _price(tmp_path / "changed.json", date="20240103")
    assert batch_import_twse(root, [changed], dry_run=False).status.tolist() == ["error"]
    (root / "prices" / "2330_202401.json").write_text("tampered")
    assert batch_import_twse(root, [row], dry_run=False).status.tolist() == ["error"]


def test_batch_recovers_interruption_and_rejects_unjournaled_orphan(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    row = _price(tmp_path / "one.json")
    target = root / "prices" / "2330_202401.json"
    from quant_fund_lab import twse_preparation
    write = twse_preparation._atomic_write

    def interrupt_manifest(path, raw):
        if path.name == "manifest.json":
            raise OSError("simulated interruption")
        return write(path, raw)

    monkeypatch.setattr(twse_preparation, "_atomic_write", interrupt_manifest)
    assert batch_import_twse(root, [row], dry_run=False).status.tolist() == ["error"]
    assert target.exists() and not (root / "manifest.json").exists()
    monkeypatch.setattr(twse_preparation, "_atomic_write", write)
    assert batch_import_twse(root, [row], dry_run=False).status.tolist() == ["imported"]
    assert batch_import_twse(root, [row]).status.tolist() == ["present"]
    other_root = tmp_path / "other"
    other_target = other_root / "prices" / target.name
    other_target.parent.mkdir(parents=True)
    other_target.write_text("unrelated")
    assert batch_import_twse(other_root, [row], dry_run=False).status.tolist() == ["error"]
    assert other_target.read_text() == "unrelated"
    assert not (other_root / "manifest.json").exists()


def test_batch_manifest_relative_paths_and_preview_validation(tmp_path):
    row = _price(tmp_path / "one.json", date="20240201")
    row["file"] = "one.json"
    manifest = tmp_path / "import.csv"
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    rows = read_batch_manifest(manifest)
    assert Path(rows[0]["file"]) == tmp_path / "one.json"
    preview = batch_import_twse(tmp_path / "bundle", rows)
    assert preview.status.tolist() == ["error"]
    assert "月份" in preview.detail.iloc[0]


def test_unfilled_checklist_rows_do_not_block_valid_imports(tmp_path):
    row = _price(tmp_path / "one.json")
    result = batch_import_twse(tmp_path / "bundle", [{**row, "file": ""}, row], dry_run=False)
    assert result.status.tolist() == ["error", "imported"]


def test_quality_groups_preserve_issues_and_link_only_known_month_gap():
    issues = [
        TWSEIssue("2024-01-01", "2024-01-31", "2330.TW", "缺少該月官方價量檔"),
        TWSEIssue("2024-01-02", "2024-01-02", "2330.TW", "缺少價格；請補官方資料或有來源的停牌紀錄"),
        TWSEIssue("2024-01-02", "2024-01-02", "2317.TW", "缺少價格；請補官方資料或有來源的停牌紀錄"),
    ]
    summary, details = summarize_quality_issues(issues)
    assert len(details) == len(issues)
    assert details.dependent_on.tolist() == ["", "2330.TW 2024-01 缺少月價量檔", ""]
    assert summary.set_index("category").loc["逐日缺價或待核對停牌", "dependent_count"] == 1
    period = summarize_period_issues(issues, pd.bdate_range("2023-01-01", "2024-01-31"),
                                     {"validation": ("2024-01-01", "2024-12-31")})
    assert period.iloc[0].issues == 3
    assert period.iloc[0].prior_observations == 120


def test_market_day_gap_is_only_marked_possible_when_all_symbols_lack_month():
    issues = [TWSEIssue("2024-01-01", "2024-01-31", symbol, "缺少該月官方價量檔")
              for symbol in ("2330.TW", "2317.TW")]
    issues.append(TWSEIssue("2024-01-02", "2024-01-02", "*", "交易日曆缺少整日資料；請核對休市公告"))
    _, complete = summarize_quality_issues(issues, symbols=["2330.TW", "2317.TW"])
    _, incomplete = summarize_quality_issues(issues, symbols=["2330.TW", "2317.TW", "0050.TW"])
    assert "可能" in complete.iloc[-1].dependent_on
    assert incomplete.iloc[-1].dependent_on == ""


def test_missing_source_checklist_is_deduplicated_and_has_no_fake_files():
    month = TWSEIssue("2024-01-01", "2024-01-31", "2330.TW", "缺少該月官方價量檔")
    holiday = TWSEIssue("2024-01-01", "2024-12-31", "*", "缺少該年度官方開休市索引")
    checklist = missing_source_manifest([month, month, holiday])
    assert checklist.kind.tolist() == ["price", "holiday_index"]
    assert checklist.file.tolist() == ["", ""]
    assert "stockNo=2330" in checklist.source_url.iloc[0]
    assert checklist.year.iloc[1] == "2024"


def test_empty_annual_index_requires_consistent_year_evidence(tmp_path):
    source = tmp_path / "index.json"
    source.write_text(json.dumps({"stat": "OK", "fields": ["資料日期", "股票代號"], "data": []}))
    row = {"file": str(source), "kind": "ex_right_index", "source_url": "https://www.twse.com.tw/events",
           "symbol": "", "month": "", "year": "2024"}
    root = tmp_path / "bundle"
    assert batch_import_twse(root, [row]).status.tolist() == ["error"]
    wrong = {**row, "source_url": "https://www.twse.com.tw/events?startDate=20230101"}
    assert batch_import_twse(root, [wrong]).status.tolist() == ["error"]
    correct = {**row, "source_url": "https://www.twse.com.tw/events?startDate=20240101&endDate=20241231"}
    assert batch_import_twse(root, [correct], dry_run=False).status.tolist() == ["imported"]
