"""Local batch imports and readable diagnostics for TWSE research bundles."""
from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import pandas as pd

from .twse_odd_lot import (
    ETF_SPLIT_URL,
    EVENT_URL,
    HOLIDAY_URL,
    MANUAL_FILES,
    PAR_CHANGE_URL,
    PRICE_URL,
    REDUCTION_URL,
    TWSEIssue,
    _date,
    _decode,
    _field,
    _official_url,
    _read_table,
    _safe_file,
    _sha,
    _symbol,
)

BATCH_COLUMNS = ("file", "kind", "source_url", "symbol", "month", "year")
INDEX_KINDS = {"ex_right_index", "etf_split_index", "par_change_index", "reduction_index", "holiday_index"}


def read_batch_manifest(path: str | Path) -> list[dict[str, str]]:
    """Read an explicit local-file inventory; relative paths are relative to the CSV."""
    manifest = Path(path).resolve()
    with manifest.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not set(BATCH_COLUMNS).issubset(reader.fieldnames or []):
            raise ValueError(f"批次清單需要欄位：{', '.join(BATCH_COLUMNS)}")
        rows = []
        for row in reader:
            item = {name: (row.get(name) or "").strip() for name in BATCH_COLUMNS}
            if item["file"]:
                file = Path(item["file"]).expanduser()
                item["file"] = str(file if file.is_absolute() else manifest.parent / file)
            rows.append(item)
    return rows


def _candidate(row: dict[str, str]) -> tuple[Path, dict, str, bytes]:
    source = Path(row.get("file", ""))
    url, kind = row.get("source_url", "").strip(), row.get("kind", "").strip()
    if not _official_url(url):
        raise ValueError("來源必須是 HTTPS 證交所網址")
    if source.suffix.lower() not in {".csv", ".json"} or not source.is_file():
        raise ValueError("來源檔案不存在或不是 JSON/CSV")
    raw = source.read_bytes()
    fields, rows = _read_table(source)
    if source.read_bytes() != raw:
        raise ValueError("來源檔案在驗證期間變更")
    if kind == "price":
        symbol = _symbol(row.get("symbol", ""))
        month = pd.Period(row.get("month", ""), freq="M")
        if pd.isna(month):
            raise ValueError("價格月份無效")
        for name in ("日期", "開盤價", "收盤價", "成交股數"):
            _field(fields, name)
        text = _decode(raw)
        if source.suffix.lower() == ".json":
            payload = json.loads(text)
            heading, response_date = str(payload.get("title", "")), str(payload.get("date", ""))
            if response_date and response_date[:6] != month.strftime("%Y%m"):
                raise ValueError("價格回應日期與月份不符")
        else:
            heading = "\n".join(text.splitlines()[:4])
        if not re.search(rf"(?<!\d){re.escape(symbol[:-3])}(?!\d)", heading):
            raise ValueError("價格來源標題與股票代碼不符")
        date_column = _field(fields, "日期")
        seen = set()
        for values in rows:
            try:
                date = _date(values[date_column])
            except (ValueError, TypeError, IndexError):
                if source.suffix.lower() == ".csv":
                    continue
                raise ValueError("價格來源有無法解析的日期") from None
            if pd.isna(date) or date.to_period("M") != month or date in seen:
                raise ValueError("價格日期與月份不符或重複")
            seen.add(date)
        info = {"kind": kind, "symbol": symbol, "month": str(month)}
        name = f"prices/{symbol[:-3]}_{month.strftime('%Y%m')}{source.suffix.lower()}"
    elif kind in INDEX_KINDS:
        year = int(row.get("year", ""))
        if not 1911 < year < 9999:
            raise ValueError("索引必須指定有效西元年度")
        date_column = _field(fields, "資料日期", "日期", "恢復買賣日期")
        if kind == "holiday_index":
            _field(fields, "名稱")
            _field(fields, "說明")
        else:
            _field(fields, "股票代號", "證券代號", "ETF代號")
        dated_rows = 0
        for values in rows:
            try:
                date = _date(values[date_column])
            except (ValueError, TypeError, IndexError):
                if source.suffix.lower() == ".csv":
                    continue
                raise ValueError("索引有無法解析的日期") from None
            if pd.isna(date) or date.year != year:
                raise ValueError("索引日期與年份不符")
            dated_rows += 1
        query = parse_qs(urlparse(url).query)
        payload = json.loads(_decode(raw)) if source.suffix.lower() == ".json" else {}
        anchors = []
        for key in ("startDate", "endDate", "date", "queryYear"):
            values = list(query.get(key, []))
            if payload.get(key) not in (None, ""):
                values.append(str(payload[key]))
            for value in values:
                if not re.fullmatch(r"\d{4}(?:\d{4})?", str(value)) or int(str(value)[:4]) != year:
                    raise ValueError("索引來源網址或回應年度與清單不符")
                anchors.append(value)
        if not dated_rows and not anchors:
            raise ValueError("空白索引缺少可核對的來源年度")
        info = {"kind": kind, "year": year}
        name = f"events/{kind}_{year}{source.suffix.lower()}"
    else:
        raise ValueError("不支援的官方資料類型")
    return source, info, name, raw


def _load_manifest(root: Path) -> dict:
    path = root / "manifest.json"
    if not path.exists():
        return {"schema_version": 1, "sources": []}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("sources"), list):
        raise ValueError("不支援的 TWSE 資料包格式")
    return manifest


def _same_key(entry: dict, info: dict) -> bool:
    return (entry.get("kind") == info["kind"] and
            (entry.get("symbol"), entry.get("month"), entry.get("year")) ==
            (info.get("symbol"), info.get("month"), info.get("year")))


def _atomic_write(path: Path, raw: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".import-", delete=False) as temp:
        temp_name = temp.name
        try:
            temp.write(raw)
            temp.flush()
            os.fsync(temp.fileno())
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
    try:
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def batch_import_twse(directory: str | Path, rows: list[dict[str, str]], *, dry_run: bool = True) -> pd.DataFrame:
    """Preview or import each source independently; identical retries are safe.

    A per-source journal preserves metadata across interruption; an unjournaled
    orphan is never silently claimed as a new official source.
    """
    root = Path(directory)
    manifest = _load_manifest(root)
    results = []
    for number, row in enumerate(rows, 1):
        result = {"row": number, "file": row.get("file", ""), "kind": row.get("kind", ""),
                  "symbol": row.get("symbol", ""), "month": row.get("month", ""),
                  "year": row.get("year", ""), "status": "error", "detail": ""}
        try:
            _, info, name, raw = _candidate(row)
            url = row["source_url"].strip()
            matches = [entry for entry in manifest["sources"] if _same_key(entry, info)]
            if len(matches) > 1:
                raise ValueError("資料包已有重複的來源身分")
            if matches:
                entry = matches[0]
                existing_hash = (entry["sha256"] if entry.get("_preview") else
                                 _sha(_safe_file(root, entry["path"]).read_bytes()))
                if (existing_hash != entry.get("sha256") or _sha(raw) != entry.get("sha256")
                        or entry.get("url") != url):
                    raise ValueError("既有來源內容、雜湊或網址衝突")
                result.update(status="duplicate" if entry.get("_preview") else "present", detail=entry["path"])
            else:
                target = root / name
                journal = target.with_name(f".{target.name}.import.json")
                if root.resolve() not in target.resolve().parents:
                    raise ValueError("來源目標路徑不安全")
                if any(entry.get("path") == name for entry in manifest["sources"]):
                    raise ValueError("來源路徑已被其他資料使用")
                entry = {**info, "path": name, "url": url, "sha256": _sha(raw),
                         "retrieved_at": datetime.now(timezone.utc).isoformat()}
                if journal.exists():
                    saved = json.loads(journal.read_text(encoding="utf-8"))
                    if any(saved.get(key) != entry.get(key) for key in (*info, "path", "url", "sha256")) or not saved.get("retrieved_at"):
                        raise ValueError("未完成匯入的來源紀錄與本次不符")
                    entry = saved
                elif target.exists():
                    raise ValueError("來源路徑已有未登記檔案；請人工核對")
                if target.exists() and (not target.is_file() or target.read_bytes() != raw):
                    raise ValueError("來源路徑已有不同的檔案")
                if not dry_run:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not journal.exists():
                        _atomic_write(journal, json.dumps(entry, ensure_ascii=False, sort_keys=True).encode())
                    if not target.exists():
                        _atomic_write(target, raw)
                    for manual_name, header in MANUAL_FILES.items():
                        manual = root / manual_name
                        if not manual.exists():
                            manual.write_text(header, encoding="utf-8")
                    updated = {**manifest, "sources": [*manifest["sources"], entry]}
                    _atomic_write(root / "manifest.json", json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True).encode())
                    manifest = updated
                    journal.unlink(missing_ok=True)
                else:
                    # Reserve the key so duplicate rows are visible during preview.
                    manifest = {**manifest, "sources": [*manifest["sources"], {**entry, "_preview": True}]}
                result.update(status="ready" if dry_run else "imported", detail=name)
        except (OSError, ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError) as exc:
            result["detail"] = str(exc)
        results.append(result)
    return pd.DataFrame(results, columns=["row", "file", "kind", "symbol", "month", "year", "status", "detail"])


def summarize_quality_issues(
    issues: list[TWSEIssue] | tuple[TWSEIssue, ...], *, symbols: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Group issues without removing or weakening any original quality gate."""
    records = [asdict(issue) if isinstance(issue, TWSEIssue) else dict(issue) for issue in issues]
    missing = {(r["symbol"], str(pd.Timestamp(r["start"]).to_period("M"))) for r in records
               if r["detail"] == "缺少該月官方價量檔"}
    for record in records:
        detail = record["detail"]
        month = str(pd.Timestamp(record["start"]).to_period("M"))
        record["month"] = month
        record["dependent_on"] = ""
        if detail == "缺少該月官方價量檔":
            category = "缺少月價量檔"
        elif detail == "缺少價格；請補官方資料或有來源的停牌紀錄":
            category = "逐日缺價或待核對停牌"
            if (record["symbol"], month) in missing:
                record["dependent_on"] = f"{record['symbol']} {month} 缺少月價量檔"
        elif detail.startswith("缺少企業行動覆蓋審核"):
            category = "企業行動覆蓋審核"
        elif "年度官方" in detail and "索引" in detail:
            category = "缺少年度索引"
        elif "企業行動" in detail or "actions.csv" in detail or "未建模" in detail:
            category = "企業行動待核對"
        elif "交易日曆" in detail or "休市" in detail or "週末" in detail:
            category = "交易日曆或休市待核對"
            if (detail == "交易日曆缺少整日資料；請核對休市公告" and symbols and
                    all((symbol, month) in missing for symbol in symbols)):
                record["dependent_on"] = f"可能與全部標的 {month} 缺少月價量檔相關；仍須核對休市"
        else:
            category = "其他"
        record["category"] = category
    columns = ["start", "end", "symbol", "detail", "month", "category", "dependent_on"]
    details = pd.DataFrame(records, columns=columns)
    if details.empty:
        return pd.DataFrame(columns=["category", "count", "dependent_count"]), details
    counts = Counter((row["category"], bool(row["dependent_on"])) for row in records)
    summary = pd.DataFrame([{"category": category, "count": sum(n for (c, _), n in counts.items() if c == category),
                             "dependent_count": counts[(category, True)]}
                            for category in sorted({r["category"] for r in records})])
    return summary, details


def missing_source_manifest(issues: list[TWSEIssue] | tuple[TWSEIssue, ...]) -> pd.DataFrame:
    """Create an editable local-import checklist; URLs are references, not provenance."""
    indexes = {
        "除權息": ("ex_right_index", EVENT_URL),
        "ETF 分割": ("etf_split_index", ETF_SPLIT_URL),
        "面額變更": ("par_change_index", PAR_CHANGE_URL),
        "減資": ("reduction_index", REDUCTION_URL),
        "開休市": ("holiday_index", HOLIDAY_URL),
    }
    rows = []
    seen = set()
    for item in issues:
        issue = asdict(item) if isinstance(item, TWSEIssue) else dict(item)
        if issue["detail"] == "缺少該月官方價量檔":
            month = pd.Timestamp(issue["start"]).to_period("M")
            symbol = _symbol(issue["symbol"])
            params = {"date": month.strftime("%Y%m01"), "stockNo": symbol[:-3], "response": "json"}
            row = {"file": "", "kind": "price", "source_url": PRICE_URL + "?" + urlencode(params),
                   "symbol": symbol, "month": str(month), "year": ""}
        else:
            matched = next(((kind, url) for label, (kind, url) in indexes.items()
                            if issue["detail"] == f"缺少該年度官方{label}索引"), None)
            if matched is None:
                continue
            kind, url = matched
            year = pd.Timestamp(issue["start"]).year
            params = ({"date": f"{year}0101", "response": "json"} if kind == "holiday_index" else
                      {"startDate": f"{year}0101", "endDate": f"{year}1231", "response": "json"})
            row = {"file": "", "kind": kind, "source_url": url + "?" + urlencode(params),
                   "symbol": "", "month": "", "year": str(year)}
        key = (row["kind"], row["symbol"], row["month"], row["year"])
        if key not in seen:
            seen.add(key)
            rows.append(row)
    return pd.DataFrame(rows, columns=BATCH_COLUMNS)


def summarize_period_issues(
    issues: list[TWSEIssue] | tuple[TWSEIssue, ...], dates: pd.DatetimeIndex,
    periods: dict, *, warmup: int = 120, coverage_end: str | None = None,
) -> pd.DataFrame:
    """Estimate each period's issue window using the observations currently available.

    Missing sessions can move the estimated start; the research gate remains the
    authority and this table never certifies warm-up completeness.
    """
    if warmup < 1:
        raise ValueError("暖機交易日數必須為正數")
    index = pd.DatetimeIndex(dates).sort_values().unique()
    records = [asdict(issue) if isinstance(issue, TWSEIssue) else dict(issue) for issue in issues]
    rows = []
    for period, (start, end) in periods.items():
        first = pd.Timestamp(start)
        last = pd.Timestamp(end or coverage_end or (index.max() if len(index) else start))
        pos = int(index.searchsorted(first, side="left"))
        window_start = index[max(0, pos - warmup)] if len(index) else first
        relevant = [r for r in records if pd.Timestamp(r["start"]) <= last and pd.Timestamp(r["end"]) >= window_start]
        rows.append({"period": period, "start": str(first.date()), "end": str(last.date()),
                     "estimated_warmup_start": str(window_start.date()),
                     "prior_observations": min(pos, warmup), "required_warmup": warmup,
                     "issues": len(relevant)})
    return pd.DataFrame(rows)
