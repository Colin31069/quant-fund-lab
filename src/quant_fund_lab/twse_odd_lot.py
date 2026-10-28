"""Auditable TWSE inputs for the Taiwan odd-lot study.

The exchange's ex-rights table is an event *index*, not a complete source for
all share distributions, capital reductions and ETF splits.  This adapter does
not infer missing entitlements from price changes.  A reviewed, sourced event
and coverage file is required in addition to the exchange responses.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from .data import MarketData

PRICE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
EVENT_URL = "https://www.twse.com.tw/rwd/zh/exRight/TWT49U"
ETF_SPLIT_URL = "https://www.twse.com.tw/rwd/zh/split/TWTCAU"
PAR_CHANGE_URL = "https://www.twse.com.tw/rwd/zh/change/TWTB8U"
REDUCTION_URL = "https://www.twse.com.tw/rwd/zh/reducation/TWTAUU"
HOLIDAY_URL = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule"
MANUAL_FILES = {
    "actions.csv": "date,symbol,split_ratio,cash_dividend,source_url,evidence_path\n",
    "suspensions.csv": "date,symbol,source_url,evidence_path\n",
    "coverage.csv": "symbol,start,end,source_url,evidence_path\n",
    "coverage_reviews.csv": "symbol,start,end,category,source_url,evidence_path\n",
}

COVERAGE_CATEGORIES = ("ex_rights", "split", "par_value", "reduction", "other_rights")


@dataclass(frozen=True)
class TWSEIssue:
    start: str
    end: str
    symbol: str
    detail: str


@dataclass(frozen=True)
class TWSEInput:
    data: MarketData
    issues: tuple[TWSEIssue, ...]
    source_files: dict[str, Path]
    source_hashes: dict[str, str]
    provenance: dict[str, str]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_file(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if root.resolve() not in path.parents or not path.is_file():
        raise ValueError(f"來源檔案不存在或路徑不安全：{name}")
    return path


def _official_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == "twse.com.tw" or host.endswith(".twse.com.tw"))


def _action_url(value: str, symbol: str) -> bool:
    if _official_url(value):
        return True
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        return False
    return (host == "taifex.com.tw" or host.endswith(".taifex.com.tw")
            or (symbol == "2881.TW" and host == "fubon.irpro.co"))


def _symbol(value: str) -> str:
    text = str(value).strip().upper()
    if not re.fullmatch(r"\d{4,6}\.TW", text):
        raise ValueError(f"只支援證交所上市代碼（例如 2330.TW）：{text}")
    return text


def _date(value: object) -> pd.Timestamp:
    text = str(value).strip().replace("年", "/").replace("月", "/").replace("日", "")
    parts = text.split("/")
    if len(parts) == 3 and parts[0].strip().isdigit():
        year = int(parts[0])
        if year < 1911:
            year += 1911
        return pd.Timestamp(year=year, month=int(parts[1]), day=int(parts[2]))
    return pd.Timestamp(text).normalize()


def _number(value: object) -> float:
    text = str(value).strip().replace(",", "")
    if text in {"", "--", "---", "-", "nan", "None"}:
        return float("nan")
    return float(text)


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp950")


def _read_table(path: Path) -> tuple[list[str], list[list[str]]]:
    """Read a TWSE JSON response or an official downloaded CSV table."""
    raw = path.read_bytes()
    text = _decode(raw)
    if text.lstrip().startswith("{"):
        obj = json.loads(text)
        if str(obj.get("stat", "")).upper() != "OK":
            raise ValueError(f"證交所回應非成功：{obj.get('stat')}")
        if not isinstance(obj.get("fields"), list) or not isinstance(obj.get("data"), list):
            raise ValueError("證交所回應缺少 fields/data")
        return list(obj["fields"]), list(obj["data"])
    rows = list(csv.reader(io.StringIO(text)))
    for i, row in enumerate(rows):
        if "日期" in row or "資料日期" in row or "恢復買賣日期" in row:
            fields = [v.strip() for v in row]
            return fields, [row for row in rows[i + 1:] if len(row) >= len(fields)]
    raise ValueError("官方 CSV 找不到日期欄位")


def import_twse_file(
    directory: str | Path, file: str | Path, *, kind: str, source_url: str,
    symbol: str = "", month: str = "", year: int = 0,
) -> Path:
    """Add an official downloaded JSON/CSV to a bundle without replacing files."""
    if not _official_url(source_url):
        raise ValueError("匯入來源必須是 HTTPS 證交所網址")
    source = Path(file)
    if source.suffix.lower() not in {".json", ".csv"}:
        raise ValueError("只接受證交所 JSON 或 CSV 檔案")
    fields, _ = _read_table(source)
    if kind == "price":
        symbol = _symbol(symbol)
        period = pd.Period(month, freq="M")
        for column in ("日期", "開盤價", "收盤價", "成交股數"):
            _field(fields, column)
        name = f"prices/{symbol[:-3]}_{period.strftime('%Y%m')}{source.suffix.lower()}"
        info = {"kind": "price", "symbol": symbol, "month": str(period)}
    elif kind in {"ex_right_index", "etf_split_index", "par_change_index", "reduction_index", "holiday_index"}:
        if not 1911 < int(year) < 9999:
            raise ValueError("企業行動索引必須指定西元年度")
        _field(fields, "資料日期", "日期", "恢復買賣日期")
        if kind == "holiday_index":
            _field(fields, "名稱")
            _field(fields, "說明")
        else:
            _field(fields, "股票代號", "證券代號", "ETF代號")
        name = f"events/{kind}_{year}{source.suffix.lower()}"
        info = {"kind": kind, "year": int(year)}
    else:
        raise ValueError("不支援的官方資料類型")
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"schema_version": 1, "sources": []}
    if manifest.get("schema_version") != 1:
        raise ValueError("不支援的 TWSE 資料包版本")
    if any(e.get("path") == name or (kind == "price" and e.get("kind") == kind and e.get("symbol") == symbol and e.get("month") == str(period)) or (kind != "price" and e.get("kind") == kind and e.get("year") == year) for e in manifest["sources"]):
        raise ValueError(f"該來源已存在：{name}")
    target = root / name
    if target.exists():
        raise FileExistsError(target)
    raw = source.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    manifest["sources"].append({**info, "path": name, "url": source_url, "sha256": _sha(raw), "retrieved_at": datetime.now(timezone.utc).isoformat()})
    tmp = root / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(manifest_path)
    for manual_name, header in MANUAL_FILES.items():
        manual = root / manual_name
        if not manual.exists():
            manual.write_text(header, encoding="utf-8")
    return target


def _field(fields: list[str], *names: str) -> int:
    for name in names:
        if name in fields:
            return fields.index(name)
    raise ValueError(f"官方資料缺少欄位：{'/'.join(names)}")


def download_twse_bundle(
    directory: str | Path, symbols: list[str], start: str, end: str, *,
    authorized: bool = False, delay: float = 1.0,
) -> Path:
    """Fetch monthly prices and yearly ex-rights indexes, retaining source bytes.

    Previously fetched files are hash checked and reused.  Manual CSV files are
    never overwritten.  Downloading does not assert non-distribution coverage.
    """
    if authorized is not True:
        raise PermissionError("證交所網站條款限制自動化下載；須先確認證交所同意此存取方式")
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    symbols = list(dict.fromkeys(_symbol(s) for s in symbols))
    first, last = _date(start), _date(end)
    if last < first or not symbols:
        raise ValueError("資料期間或標的不正確")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"schema_version": 1, "sources": []}
    if manifest.get("schema_version") != 1:
        raise ValueError("不支援的 TWSE 資料包版本")
    for name, header in MANUAL_FILES.items():
        path = root / name
        if not path.exists():
            path.write_text(header, encoding="utf-8")

    requests: list[tuple[str, str, dict]] = []
    for year in range(first.year, last.year + 1):
        params = {"startDate": f"{year}0101", "endDate": f"{year}1231", "response": "json"}
        for prefix, url, kind in (("ex_right", EVENT_URL, "ex_right_index"),
                                  ("etf_split", ETF_SPLIT_URL, "etf_split_index"),
                                  ("par_change", PAR_CHANGE_URL, "par_change_index"),
                                  ("reduction", REDUCTION_URL, "reduction_index")):
            name = f"events/{prefix}_{year}.json"
            requests.append((name, url + "?" + urlencode(params), {"kind": kind, "year": year}))
        holiday_params = {"date": f"{year}0101", "response": "json"}
        requests.append((f"events/holiday_{year}.json", HOLIDAY_URL + "?" + urlencode(holiday_params),
                         {"kind": "holiday_index", "year": year}))
    for month in pd.period_range(first, last, freq="M"):
        for symbol in symbols:
            name = f"prices/{symbol[:-3]}_{month.strftime('%Y%m')}.json"
            params = {"date": month.strftime("%Y%m01"), "stockNo": symbol[:-3], "response": "json"}
            requests.append((name, PRICE_URL + "?" + urlencode(params), {"kind": "price", "symbol": symbol, "month": str(month)}))

    for name, url, info in requests:
        matching = next((entry for entry in manifest["sources"]
                         if entry.get("kind") == info["kind"]
                         and (entry.get("symbol"), entry.get("month"), entry.get("year"))
                         == (info.get("symbol"), info.get("month"), info.get("year"))), None)
        if matching:
            existing = _safe_file(root, matching["path"])
            if _sha(existing.read_bytes()) != matching["sha256"]:
                raise ValueError(f"原始來源檔案雜湊不符：{matching['path']}")
            retrieved = datetime.fromisoformat(matching["retrieved_at"].replace("Z", "+00:00"))
            if retrieved.tzinfo is None:
                raise ValueError(f"來源取得時間缺少時區：{matching['path']}")
            retrieved_date = retrieved.astimezone(timezone(timedelta(hours=8))).date()
            current_period = (info.get("month") == str(last.to_period("M")) if info["kind"] == "price"
                              else info.get("year") == last.year)
            refresh = current_period and retrieved_date <= last.date()
            if not refresh:
                continue
        req = Request(url, headers={"User-Agent": "QuantFundLab research/1.0", "Accept": "application/json"})
        try:
            for attempt in range(3):
                try:
                    with urlopen(req, timeout=30) as response:
                        raw = response.read()
                    break
                except (HTTPError, URLError, TimeoutError) as exc:
                    if attempt == 2 or (isinstance(exc, HTTPError) and exc.code not in {429, 500, 502, 503, 504}):
                        raise
                    retry_after = exc.headers.get("Retry-After", "") if isinstance(exc, HTTPError) else ""
                    wait = float(retry_after) if retry_after.isdigit() else 2.0 ** (attempt + 1)
                    time.sleep(min(wait, 30))
            obj = json.loads(raw.decode("utf-8-sig"))
            if str(obj.get("stat", "")).upper() != "OK" or not isinstance(obj.get("data"), list):
                raise ValueError(f"回應非成功或缺少資料：{obj.get('stat')}")
            if info["kind"] == "holiday_index" and str(obj.get("queryYear")) != str(info["year"]):
                raise ValueError("休市日曆回應年份與查詢不符")
        except Exception as exc:
            raise RuntimeError(f"下載失敗 {url}：{exc}；已下載檔案保留，可稍後重試") from exc
        if matching:
            # Keep the previous response immutable for any already-frozen study.
            if info["kind"] == "price":
                name = f"prices/{info['symbol'][:-3]}_{info['month'].replace('-', '')}_{_sha(raw)[:16]}.json"
            else:
                name = f"events/{info['kind']}_{info['year']}_{_sha(raw)[:16]}.json"
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != raw:
            raise ValueError(f"來源快取檔衝突：{name}")
        if not path.exists():
            path.write_bytes(raw)
        entry = {**info, "path": name, "url": url, "sha256": _sha(raw), "retrieved_at": datetime.now(timezone.utc).isoformat()}
        if matching:
            manifest["sources"].remove(matching)
        manifest["sources"].append(entry)
        tmp = root / "manifest.json.tmp"
        tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(manifest_path)
        if delay > 0:
            time.sleep(delay)
    return manifest_path


def _manual_rows(root: Path, name: str, required: set[str]) -> list[dict[str, str]]:
    path = _safe_file(root, name)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(f"{name} 缺少欄位：{', '.join(sorted(required))}")
        return list(reader)


def populate_cash_dividends(directory: str | Path, symbols: list[str]) -> int:
    """Add unambiguous cash-only events from downloaded TWSE result tables.

    Existing reviewed rows are preserved; share distributions, splits and
    special rights require their own sourced records.
    """
    root = Path(directory)
    symbols = {_symbol(s) for s in symbols}
    required = {"date", "symbol", "split_ratio", "cash_dividend", "source_url", "evidence_path"}
    rows = _manual_rows(root, "actions.csv", required)
    existing = {(_date(row["date"]), _symbol(row["symbol"])) for row in rows}
    manifest = json.loads(_safe_file(root, "manifest.json").read_text(encoding="utf-8"))
    additions: list[dict[str, str]] = []
    for entry in manifest["sources"]:
        if entry.get("kind") != "ex_right_index":
            continue
        path = _safe_file(root, entry["path"])
        raw = path.read_bytes()
        if _sha(raw) != entry.get("sha256") or not _official_url(str(entry.get("url", ""))):
            raise ValueError(f"除權息來源未通過驗證：{entry['path']}")
        fields, data = _read_table(path)
        if not {"資料日期", "股票代號", "權/息", "權值+息值"}.issubset(fields):
            continue
        for values in data:
            date = _date(values[_field(fields, "資料日期")])
            symbol = str(values[_field(fields, "股票代號")]).strip() + ".TW"
            if symbol not in symbols or (date, symbol) in existing:
                continue
            amount = _number(values[_field(fields, "權值+息值")])
            if str(values[_field(fields, "權/息")]).strip() != "息" or not np.isfinite(amount) or amount <= 0:
                continue
            name = f"evidence/ex_right_{entry['year']}_{_sha(raw)[:16]}{path.suffix.lower()}"
            evidence_path = root / name
            if evidence_path.exists() and evidence_path.read_bytes() != raw:
                raise ValueError(f"既有佐證與官方來源不同：{name}")
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            if not evidence_path.exists():
                evidence_path.write_bytes(raw)
            additions.append({"date": str(date.date()), "symbol": symbol, "split_ratio": "1",
                              "cash_dividend": str(amount), "source_url": entry["url"],
                              "evidence_path": name})
            existing.add((date, symbol))
    columns = ["date", "symbol", "split_ratio", "cash_dividend", "source_url", "evidence_path"]
    tmp = root / "actions.csv.tmp"
    with tmp.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows + additions)
    tmp.replace(root / "actions.csv")
    return len(additions)


def _total_return(raw_close: pd.DataFrame, dividends: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    """Forward total-return index; no later action can revise an earlier row."""
    result = pd.DataFrame(np.nan, index=raw_close.index, columns=raw_close.columns)
    for symbol in raw_close.columns:
        previous = float("nan")
        index_value = float("nan")
        for date in raw_close.index:
            price = raw_close.at[date, symbol]
            dividend = dividends.at[date, symbol]
            split = splits.at[date, symbol]
            if pd.isna(price) or pd.isna(dividend) or pd.isna(split):
                previous = index_value = float("nan")
                continue
            ratio = float(split) if split > 0 else 1.0
            if pd.isna(previous):
                index_value = float(price)
            else:
                index_value *= (float(price) * ratio + float(dividend)) / previous
            result.at[date, symbol] = index_value
            previous = float(price)
    return result


def prepare_twse_odd_lot(
    directory: str | Path, symbols: list[str], start: str, end: str
) -> TWSEInput:
    """Normalize a TWSE bundle and report all known gaps without guessing.

    Coverage attestations document a manual review; they are not proof of a
    historically point-in-time vendor feed or executable odd-lot quotations.
    """
    root = Path(directory)
    symbols = list(dict.fromkeys(_symbol(s) for s in symbols))
    first, last = _date(start), _date(end)
    if last < first or not symbols:
        raise ValueError("資料期間或標的不正確")
    manifest_path = _safe_file(root, "manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("sources"), list):
        raise ValueError("不支援的 TWSE 資料包格式")
    source_files: dict[str, Path] = {"manifest.json": manifest_path}
    issues: list[TWSEIssue] = []
    prices: dict[str, dict[pd.Timestamp, tuple[float, float, float]]] = {s: {} for s in symbols}
    seen_price_dates: dict[str, set[pd.Timestamp]] = {s: set() for s in symbols}
    covered_prices: set[tuple[str, str]] = set()
    event_years: set[tuple[str, int]] = set()
    indexed_events: set[tuple[pd.Timestamp, str]] = set()
    seen_index_rows: set[tuple[str, pd.Timestamp, str]] = set()
    indexed_details: dict[tuple[pd.Timestamp, str], tuple[float, float, str, float]] = {}
    unsupported_events: set[tuple[pd.Timestamp, str]] = set()
    flagged_resumptions: set[tuple[pd.Timestamp, str]] = set()
    official_closures: set[pd.Timestamp] = set()
    seen_paths: set[str] = set()
    for entry in manifest["sources"]:
        name = str(entry.get("path", ""))
        if name in seen_paths:
            raise ValueError(f"重複來源檔案：{name}")
        seen_paths.add(name)
        path = _safe_file(root, name)
        if _sha(path.read_bytes()) != entry.get("sha256"):
            raise ValueError(f"原始來源檔案雜湊不符：{name}")
        if not _official_url(str(entry.get("url", ""))) or not entry.get("retrieved_at"):
            raise ValueError(f"來源缺少證交所網址或取得時間：{name}")
        source_files[name] = path
        fields, rows = _read_table(path)
        kind = entry.get("kind")
        if kind == "price":
            symbol, month = _symbol(entry["symbol"]), str(entry["month"])
            if symbol not in prices:
                continue
            if path.suffix.lower() == ".json":
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
                title = str(payload.get("title", ""))
                response_date = str(payload.get("date", ""))
                if response_date and response_date[:6] != month.replace("-", ""):
                    raise ValueError(f"價格回應日期與來源月份不符：{name}")
                if not re.search(rf"(?<!\d){re.escape(symbol[:-3])}(?!\d)", title):
                    raise ValueError(f"價格來源標題與股票代碼不符：{name}")
            else:
                heading = "\n".join(_decode(path.read_bytes()).splitlines()[:4])
                if not re.search(rf"(?<!\d){re.escape(symbol[:-3])}(?!\d)", heading):
                    raise ValueError(f"價格來源標題與股票代碼不符：{name}")
            key = (symbol, month)
            if key in covered_prices:
                raise ValueError(f"重複股票月份：{symbol} {month}")
            covered_prices.add(key)
            di, oi, ci, vi = (_field(fields, "日期"), _field(fields, "開盤價"), _field(fields, "收盤價"), _field(fields, "成交股數"))
            for row in rows:
                try:
                    date = _date(row[di])
                except (ValueError, TypeError, IndexError) as exc:
                    if path.suffix.lower() == ".json":
                        raise ValueError(f"價格來源有無法解析的日期：{name}") from exc
                    continue  # Official CSV footers are not data rows.
                if str(date.to_period("M")) != month:
                    raise ValueError(f"價格日期與來源月份不符：{symbol} {date.date()}")
                if date in seen_price_dates[symbol]:
                    raise ValueError(f"重複價格：{symbol} {date.date()}")
                seen_price_dates[symbol].add(date)
                if "註記" in fields and str(row[_field(fields, "註記")]).strip() == "**":
                    flagged_resumptions.add((date, symbol))
                opening, close, volume = _number(row[oi]), _number(row[ci]), _number(row[vi])
                if not all(np.isfinite(x) and x > 0 for x in (opening, close, volume)):
                    continue
                prices[symbol][date] = (opening, close, volume)
        elif kind == "holiday_index":
            year = int(entry["year"])
            if (kind, year) in event_years:
                raise ValueError(f"重複休市日曆年度：{year}")
            event_years.add((kind, year))
            di, ni, ei = _field(fields, "日期"), _field(fields, "名稱"), _field(fields, "說明")
            for row in rows:
                try:
                    date, name, explanation = _date(row[di]), str(row[ni]), str(row[ei])
                except (ValueError, TypeError, IndexError) as exc:
                    if path.suffix.lower() == ".json":
                        raise ValueError(f"官方日曆有無法解析的資料：{name}") from exc
                    continue
                if date.year != year:
                    raise ValueError(f"休市日期與來源年度不符：{date.date()}")
                if "休市" in name or "無交易" in name or "放假" in explanation:
                    official_closures.add(date)
        elif kind in {"ex_right_index", "etf_split_index", "par_change_index", "reduction_index"}:
            year = int(entry["year"])
            if (kind, year) in event_years:
                raise ValueError(f"重複企業行動索引年度：{kind} {year}")
            event_years.add((kind, year))
            di = _field(fields, "資料日期", "日期", "恢復買賣日期")
            si = _field(fields, "股票代號", "證券代號", "ETF代號")
            for row in rows:
                try:
                    date, symbol = _date(row[di]), str(row[si]).strip() + ".TW"
                except (ValueError, TypeError, IndexError) as exc:
                    if path.suffix.lower() == ".json":
                        raise ValueError(f"企業行動來源有無法解析的日期或代碼：{name}") from exc
                    continue
                if date.year != year:
                    raise ValueError(f"除權息資料日期與年度不符：{date.date()}")
                if symbol in prices and first <= date <= last:
                    index_key = (kind, date, symbol)
                    if index_key in seen_index_rows:
                        raise ValueError(f"重複企業行動索引：{kind} {symbol} {date.date()}")
                    seen_index_rows.add(index_key)
                    indexed_events.add((date, symbol))
                    if kind == "reduction_index":
                        unsupported_events.add((date, symbol))
                    if kind == "ex_right_index" and "除權息參考價" in fields and "減除股利參考價" in fields:
                        reference = _number(row[_field(fields, "除權息參考價")])
                        dividend_reference = _number(row[_field(fields, "減除股利參考價")])
                        if np.isfinite(reference) and np.isfinite(dividend_reference) and abs(reference - dividend_reference) > 0.011:
                            unsupported_events.add((date, symbol))
                        if "除權息前收盤價" in fields and "權/息" in fields and "權值+息值" in fields:
                            indexed_details[(date, symbol)] = (
                                _number(row[_field(fields, "除權息前收盤價")]), dividend_reference,
                                str(row[_field(fields, "權/息")]).strip(),
                                _number(row[_field(fields, "權值+息值")]),
                            )
        else:
            raise ValueError(f"不支援的來源類型：{kind}")

    for name in MANUAL_FILES:
        # Older bundles can be inspected without creating or silently certifying reviews.
        if name != "coverage_reviews.csv" or (root / name).exists():
            source_files[name] = _safe_file(root, name)
    actions = _manual_rows(root, "actions.csv", {"date", "symbol", "split_ratio", "cash_dividend", "source_url", "evidence_path"})
    suspensions = _manual_rows(root, "suspensions.csv", {"date", "symbol", "source_url", "evidence_path"})
    coverage = (_manual_rows(root, "coverage_reviews.csv", {"symbol", "start", "end", "category", "source_url", "evidence_path"})
                if (root / "coverage_reviews.csv").exists() else [])
    def evidence(row: dict[str, str]) -> None:
        name = row.get("evidence_path", "").strip()
        if not name.startswith("evidence/"):
            raise ValueError("佐證檔案必須位於資料包 evidence/ 目錄")
        source_files[name] = _safe_file(root, name)
    action_map: dict[tuple[pd.Timestamp, str], tuple[float, float]] = {}
    for row in actions:
        date, symbol = _date(row["date"]), _symbol(row["symbol"])
        ratio, dividend = _number(row["split_ratio"]), _number(row["cash_dividend"])
        if not _action_url(row["source_url"], symbol) or not np.isfinite(ratio) or ratio <= 0 or not np.isfinite(dividend) or dividend < 0 or (ratio == 1 and dividend == 0):
            raise ValueError(f"企業行動無效或缺少可核對的官方來源：{symbol} {date.date()}")
        evidence(row)
        key = (date, symbol)
        if key in action_map:
            raise ValueError(f"重複企業行動：{symbol} {date.date()}")
        action_map[key] = (ratio, dividend)
    suspension_set: set[tuple[pd.Timestamp, str]] = set()
    for row in suspensions:
        date, symbol = _date(row["date"]), row["symbol"].strip().upper()
        if symbol != "*":
            symbol = _symbol(symbol)
        if not _official_url(row["source_url"]):
            raise ValueError(f"停牌/休市資料缺少證交所來源：{symbol} {date.date()}")
        evidence(row)
        if (date, symbol) in suspension_set:
            raise ValueError(f"重複停牌：{symbol} {date.date()}")
        suspension_set.add((date, symbol))
    reviewed: dict[tuple[str, str], list[tuple[pd.Timestamp, pd.Timestamp]]] = {
        (s, category): [] for s in symbols for category in COVERAGE_CATEGORIES
    }
    for row in coverage:
        symbol = _symbol(row["symbol"])
        a, b = _date(row["start"]), _date(row["end"])
        category = row["category"].strip()
        if (not _official_url(row["source_url"]) or pd.isna(a) or pd.isna(b)
                or b < a or category not in COVERAGE_CATEGORIES):
            raise ValueError(f"企業行動覆蓋資料無效：{symbol}")
        evidence(row)
        if (symbol, category) in reviewed:
            reviewed[(symbol, category)].append((a, b))

    for month in pd.period_range(first, last, freq="M"):
        a, b = max(first, month.start_time), min(last, month.end_time.normalize())
        for symbol in symbols:
            if (symbol, str(month)) not in covered_prices:
                issues.append(TWSEIssue(str(a.date()), str(b.date()), symbol, "缺少該月官方價量檔"))
    for year in range(first.year, last.year + 1):
        for kind, label in (("ex_right_index", "除權息"), ("etf_split_index", "ETF 分割"),
                            ("par_change_index", "面額變更"), ("reduction_index", "減資"),
                            ("holiday_index", "開休市")):
            if (kind, year) not in event_years:
                issues.append(TWSEIssue(str(max(first, pd.Timestamp(year, 1, 1)).date()), str(min(last, pd.Timestamp(year, 12, 31)).date()), "*", f"缺少該年度官方{label}索引"))
    for symbol in symbols:
        for category in COVERAGE_CATEGORIES:
            # Each category requires its own continuous human-reviewed evidence.
            cursor = first
            for a, b in sorted(reviewed[(symbol, category)]):
                if b < cursor:
                    continue
                if a > cursor:
                    issues.append(TWSEIssue(str(cursor.date()), str(min(last, a - pd.Timedelta(days=1)).date()), symbol, f"缺少企業行動覆蓋審核：{category}"))
                cursor = max(cursor, b + pd.Timedelta(days=1))
                if cursor > last:
                    break
            if cursor <= last:
                issues.append(TWSEIssue(str(cursor.date()), str(last.date()), symbol, f"缺少企業行動覆蓋審核：{category}"))
    for date, symbol in sorted((indexed_events | flagged_resumptions) - set(action_map)):
        issues.append(TWSEIssue(str(date.date()), str(date.date()), symbol, "官方企業行動索引或恢復交易註記有事件，actions.csv 缺少有來源的配股率/股利"))
    for date, symbol in sorted(unsupported_events):
        issues.append(TWSEIssue(str(date.date()), str(date.date()), symbol, "減資或官方參考價顯示可能含現金增資等未建模權利，不能僅按配股/股利計算"))
    for key in sorted(indexed_details.keys() & action_map.keys()):
        before, reference, category, amount = indexed_details[key]
        ratio, dividend = action_map[key]
        calculated = (before - dividend) / ratio
        inconsistent = np.isfinite(before) and np.isfinite(reference) and abs(calculated - reference) > 0.03
        if category == "息" and np.isfinite(amount):
            inconsistent = inconsistent or ratio != 1.0 or abs(amount - dividend) > 0.00001
        if inconsistent:
            date, symbol = key
            issues.append(TWSEIssue(str(date.date()), str(date.date()), symbol, "配股/股利與官方除權息資料不一致"))

    observed = sorted({d for values in prices.values() for d in values if first <= d <= last})
    if not observed:
        raise ValueError("指定期間沒有任何官方價量資料；請先下載或匯入")
    index = pd.DatetimeIndex(observed)
    for (date, symbol), _ in sorted(action_map.items()):
        if symbol in prices and first <= date <= last and date not in prices[symbol]:
            issues.append(TWSEIssue(str(date.date()), str(date.date()), symbol, "企業行動日缺少可核對的價量；無法安全估值"))
    # A whole-market omission also needs an explicit official closure explanation.
    calendar = xcals.get_calendar("XTAI")
    expected_sessions = calendar.sessions_in_range(first, last).tz_localize(None).normalize()
    for date in expected_sessions.difference(index):
        if first <= date <= last and date not in official_closures and (date, "*") not in suspension_set:
            issues.append(TWSEIssue(str(date.date()), str(date.date()), "*", "交易日曆缺少整日資料；請核對休市公告"))
    for date in index:
        if date in official_closures or (date, "*") in suspension_set:
            issues.append(TWSEIssue(str(date.date()), str(date.date()), "*", "休市紀錄與官方成交價量衝突"))
        if date.weekday() >= 5:
            issues.append(TWSEIssue(str(date.date()), str(date.date()), "*", "週末交易日尚未支援，請核對官方交易日曆"))
    raw_open = pd.DataFrame(np.nan, index=index, columns=symbols)
    raw_close = raw_open.copy()
    volume = pd.DataFrame(0.0, index=index, columns=symbols)
    dividends = volume.copy()
    splits = volume.copy()
    for symbol in symbols:
        previous = float("nan")
        for date in index:
            row = prices[symbol].get(date)
            if row is not None:
                if (date, symbol) in suspension_set:
                    issues.append(TWSEIssue(str(date.date()), str(date.date()), symbol, "停牌紀錄與官方成交價量衝突"))
                opening, close, quantity = row
                raw_open.at[date, symbol], raw_close.at[date, symbol], volume.at[date, symbol] = opening, close, quantity
                previous = close
            elif (date, symbol) in suspension_set and np.isfinite(previous):
                raw_close.at[date, symbol] = previous
            else:
                issues.append(TWSEIssue(str(date.date()), str(date.date()), symbol, "缺少價格；請補官方資料或有來源的停牌紀錄"))
                previous = float("nan")
            key = (date, symbol)
            if key in (indexed_events | flagged_resumptions) and key not in action_map:
                dividends.at[date, symbol] = np.nan
                splits.at[date, symbol] = np.nan
            elif key in action_map:
                splits.at[date, symbol], dividends.at[date, symbol] = action_map[key]
    adjusted = _total_return(raw_close, dividends, splits)
    # The adjusted open is not used for execution; retain missing opens on suspensions.
    adjusted_open = raw_open * adjusted.div(raw_close)
    data = MarketData(open=adjusted_open, close=adjusted, volume=volume, raw_open=raw_open,
                      raw_close=raw_close, dividends=dividends, stock_splits=splits,
                      market_codes=pd.DataFrame("TW", index=index, columns=symbols),
                      currency_codes=pd.DataFrame("TWD", index=index, columns=symbols),
                      base_currency="TWD", exchange="TW")
    hashes = {name: _sha(path.read_bytes()) for name, path in sorted(source_files.items())}
    provenance = {"source": "TWSE", "coverage_start": str(first.date()), "coverage_end": str(last.date()),
                  "source_manifest_sha256": _sha(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()),
                  "coverage_note": "manual review; historical publication and revision times are not independently verified"}
    return TWSEInput(data=data, issues=tuple(issues), source_files=source_files, source_hashes=hashes, provenance=provenance)
