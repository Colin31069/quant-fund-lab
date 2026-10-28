"""Frozen Taiwan odd-lot research inputs, period comparisons and report exports."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

import pandas as pd

from . import __version__
from .analytics import buy_and_hold_equity, performance_metrics
from .config import BacktestConfig, DividendWithholdingConfig, MarketCostConfig, StrategyConfig
from .data import MarketData
from .odd_lot_research import OddLotResearchConfig, OddLotResearchResult, run_odd_lot_research
from .snapshot import load_market_data_snapshot, save_market_data_snapshot

SAMPLE_SYMBOLS = (
    "2330.TW", "2317.TW", "2454.TW", "2308.TW", "2881.TW",
    "2882.TW", "2891.TW", "1216.TW", "1301.TW", "2412.TW",
)
SAMPLE_BENCHMARK = "0050.TW"
PERIODS = {
    "development": ("2021-01-01", "2023-12-31"),
    "validation": ("2024-01-01", "2024-12-31"),
    "historical_evaluation": ("2025-01-01", None),
}


@dataclass(frozen=True)
class OddLotStudyResult:
    study_id: str
    dataset_id: str
    comparison: pd.DataFrame
    sensitivity: pd.DataFrame
    results: dict[tuple[str, str], OddLotResearchResult]
    unavailable: dict[str, str]
    holdout_untouched: bool


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _subset(data: MarketData, symbols: list[str]) -> MarketData:
    missing = set(symbols) - set(data.symbols)
    if missing:
        raise ValueError(f"study snapshot is missing requested symbols: {sorted(missing)}")
    panels = {
        item.name: getattr(data, item.name).loc[:, symbols]
        for item in fields(data)
        if isinstance(getattr(data, item.name), pd.DataFrame)
    }
    return replace(data, **panels)


def freeze_odd_lot_study(
    data: MarketData,
    root: str | Path,
    *,
    symbols: tuple[str, ...] = SAMPLE_SYMBOLS,
    benchmark: str = SAMPLE_BENCHMARK,
    research: OddLotResearchConfig | None = None,
    base_config: BacktestConfig | None = None,
    source: str = "unspecified",
    source_provenance: dict[str, str] | None = None,
    holdout_untouched: bool = False,
) -> Path:
    """Freeze source bytes and all assumptions before running an experiment.

    Existing studies are verified and reused, never overwritten.
    """
    research = research or OddLotResearchConfig()
    base_config = base_config or BacktestConfig(initial_cash=100_000.0, base_currency="TWD")
    symbols = tuple(dict.fromkeys(symbols))
    if len(symbols) < 2 or benchmark in symbols:
        raise ValueError("study requires at least two distinct trade assets and a separate benchmark")
    data = _subset(data, [*symbols, benchmark])
    if data.close.index.has_duplicates or not data.close.index.is_monotonic_increasing:
        raise ValueError("study dates must be unique and chronological")
    parent = Path(root)
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".study-", dir=parent) as temporary:
        staging = Path(temporary) / "payload"
        snapshot = save_market_data_snapshot(data, staging / "snapshot")
        payload = {
            "schema_version": 1,
            "dataset_id": snapshot.dataset_id,
            "package_version": __version__,
            "symbols": list(symbols),
            "benchmark": benchmark,
            "research_config": asdict(research),
            "backtest_config": asdict(base_config),
            "periods": PERIODS,
            "data_source": str(source),
            "source_provenance": dict(source_provenance or {}),
            "holdout_untouched": bool(holdout_untouched),
            "liquidity_model": "prior_20_session_median_v1",
            "execution_assumption": "ordinary_open_as_odd_lot_proxy",
            "survivorship_warning": "fixed contemporary sample, not a point-in-time universe",
        }
        study_id = hashlib.sha256(_canonical(payload)).hexdigest()[:24]
        metadata = {"study_id": study_id, **payload}
        (staging / "study.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        destination = parent / study_id
        if destination.exists():
            existing = load_frozen_odd_lot_study(destination)[1]
            if _canonical(existing) != _canonical(metadata):
                raise ValueError("existing study identity conflicts with the requested assumptions")
            return destination
        os.rename(staging, destination)
        return destination


def load_frozen_odd_lot_study(directory: str | Path) -> tuple[MarketData, dict]:
    root = Path(directory)
    metadata = json.loads((root / "study.json").read_text(encoding="utf-8"))
    study_id = metadata.get("study_id")
    payload = {key: value for key, value in metadata.items() if key != "study_id"}
    if study_id != hashlib.sha256(_canonical(payload)).hexdigest()[:24]:
        raise ValueError("study configuration integrity check failed")
    data = load_market_data_snapshot(root / "snapshot")
    snapshot_manifest = json.loads((root / "snapshot" / "manifest.json").read_text(encoding="utf-8"))
    if snapshot_manifest["dataset_id"] != metadata["dataset_id"]:
        raise ValueError("study snapshot identity mismatch")
    if data.symbols != metadata["symbols"] + [metadata["benchmark"]]:
        raise ValueError("study snapshot symbols conflict with frozen configuration")
    if snapshot_manifest["start"] != str(data.close.index.min().date()) or snapshot_manifest["end"] != str(data.close.index.max().date()):
        raise ValueError("study snapshot date range conflicts with its manifest")
    return data, metadata


def _backtest_config(payload: dict) -> BacktestConfig:
    values = dict(payload)
    values["strategy"] = StrategyConfig(**values["strategy"])
    values["us_costs"] = MarketCostConfig(**values["us_costs"])
    values["tw_costs"] = MarketCostConfig(**values["tw_costs"])
    values["dividend_withholding"] = DividendWithholdingConfig(**values["dividend_withholding"])
    return BacktestConfig(**values)


def run_frozen_odd_lot_study(directory: str | Path) -> OddLotStudyResult:
    data, metadata = load_frozen_odd_lot_study(directory)
    if metadata["package_version"] != __version__:
        raise ValueError("study was frozen with a different package version; freeze a new study")
    trade_data = _subset(data, metadata["symbols"])
    base = _backtest_config(metadata["backtest_config"])
    research = OddLotResearchConfig(**metadata["research_config"])
    results: dict[tuple[str, str], OddLotResearchResult] = {}
    rows: list[dict] = []
    unavailable: dict[str, str] = {}
    for period, (start, end) in metadata["periods"].items():
        for strategy in ("ensemble", "momentum", "equal_weight"):
            try:
                result = run_odd_lot_research(trade_data, replace(research, strategy=strategy), base, start=start, end=end)
            except ValueError as exc:
                if "insufficient observations for the requested research interval" not in str(exc):
                    raise
                unavailable[f"{period}/{strategy}"] = str(exc)
                continue
            results[(period, strategy)] = result
            rows.append({"period": period, "strategy": strategy, **result.metrics, **result.trade_summary})
        reference = results.get((period, "equal_weight"))
        if reference is not None:
            index = reference.equity_curve.index
            benchmark = data.close[metadata["benchmark"]].reindex(index).ffill().dropna()
            if len(benchmark) >= 2 and benchmark.index[0] == index[0]:
                curve = buy_and_hold_equity(benchmark, base.initial_cash)
                rows.append({"period": period, "strategy": f"{metadata['benchmark']}_total_return_proxy_no_trading_costs", **performance_metrics(curve)})
            else:
                unavailable[f"{period}/benchmark"] = "benchmark lacks an observation at the interval start"

    sensitivity: list[dict] = []
    start, end = metadata["periods"]["validation"]
    for strategy in ("ensemble", "momentum"):
        if ("validation", strategy) not in results:
            continue
        for commission, slippage in ((0.0, 5.0), (20.0, 5.0), (50.0, 5.0), (20.0, 10.0)):
            scenario = replace(research, strategy=strategy, min_commission=commission, slippage_bps=slippage)
            if scenario == results[("validation", strategy)].config:
                result = results[("validation", strategy)]
            else:
                result = run_odd_lot_research(trade_data, scenario, base, start=start, end=end)
            sensitivity.append({"strategy": strategy, "min_commission": commission, "slippage_bps": slippage, **result.metrics, **result.trade_summary})
    return OddLotStudyResult(
        study_id=metadata["study_id"], dataset_id=metadata["dataset_id"],
        comparison=pd.DataFrame(rows), sensitivity=pd.DataFrame(sensitivity),
        results=results, unavailable=unavailable,
        holdout_untouched=metadata["holdout_untouched"],
    )


def export_odd_lot_study_report(directory: str | Path, study: OddLotStudyResult) -> Path:
    """Write a new, hashed report without overwriting another run."""
    root = Path(directory)
    _, metadata = load_frozen_odd_lot_study(root)
    if study.study_id != metadata["study_id"] or study.dataset_id != metadata["dataset_id"]:
        raise ValueError("study results do not match the frozen input")
    target = root / "reports" / uuid.uuid4().hex
    target.mkdir(parents=True, exist_ok=False)
    _write_account_archive(target / "study_ledger.sqlite", study)
    study.comparison.to_csv(target / "comparison.csv", index=False)
    study.sensitivity.to_csv(target / "sensitivity.csv", index=False)
    (target / "assumptions.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (target / "unavailable.json").write_text(json.dumps(study.unavailable, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (target / "report.html").write_text(
        "<!doctype html><html><head><meta charset='utf-8'><title>Odd-lot research</title>"
        "<style>body{font-family:system-ui;margin:2em}table{border-collapse:collapse}"
        "th,td{padding:.4em;border:1px solid #ccc}</style></head><body>"
        "<h1>台股零股研究</h1><p>模擬資料、普通交易開盤代理價格與歷史成交量代理；"
        "不保證實際零股成交或止損。固定現存股票池有存活者偏差。</p>"
        "<h2>分段比較</h2>" + study.comparison.to_html(index=False) +
        "<h2>成本敏感度（驗證期）</h2>" + study.sensitivity.to_html(index=False) +
        "</body></html>", encoding="utf-8"
    )
    for (period, strategy), result in study.results.items():
        prefix = f"{period}_{strategy}"
        for name in ("equity_curve", "fills", "signals", "episodes", "corporate_actions", "terminal_events"):
            getattr(result, name).to_csv(target / f"{prefix}_{name}.csv", index=name == "equity_curve")
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(target.iterdir()) if path.is_file()}
    manifest = {"study_id": study.study_id, "dataset_id": study.dataset_id, "files": hashes}
    manifest["report_id"] = hashlib.sha256(_canonical(manifest)).hexdigest()
    (target / "report_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return target


def verify_odd_lot_study_report(directory: str | Path) -> bool:
    root = Path(directory)
    manifest = json.loads((root / "report_manifest.json").read_text(encoding="utf-8"))
    report_id = manifest.pop("report_id")
    if hashlib.sha256(_canonical(manifest)).hexdigest() != report_id:
        return False
    return all((root / name).is_file() and hashlib.sha256((root / name).read_bytes()).hexdigest() == expected for name, expected in manifest["files"].items())


def _account_assumptions(result: OddLotResearchResult) -> dict:
    return {"research": asdict(result.config), "execution": asdict(result.backtest_config)}


def _write_account_archive(path: Path, study: OddLotStudyResult) -> None:
    """Archive independently reset research accounts; this is not a resumable live ledger."""
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE accounts (account_id TEXT PRIMARY KEY, study_id TEXT NOT NULL, "
            "dataset_id TEXT NOT NULL, settings_json TEXT NOT NULL, settings_sha256 TEXT NOT NULL)"
        )
        for (period, strategy), result in study.results.items():
            account_id = f"{period}/{strategy}"
            settings = _canonical(_account_assumptions(result)).decode()
            db.execute(
                "INSERT INTO accounts VALUES (?, ?, ?, ?, ?)",
                (account_id, study.study_id, study.dataset_id, settings,
                 hashlib.sha256(settings.encode()).hexdigest()),
            )
            for name in ("equity_curve", "fills", "signals", "episodes", "corporate_actions", "terminal_events"):
                frame = getattr(result, name)
                if frame.empty:
                    continue
                if name == "equity_curve":
                    frame = frame.reset_index()
                frame = frame.copy()
                frame.insert(0, "account_id", account_id)
                frame.to_sql(name, db, if_exists="append", index=False)
        db.execute("CREATE TRIGGER no_account_update BEFORE UPDATE ON accounts BEGIN SELECT RAISE(ABORT, 'account settings are locked'); END")
        db.execute("CREATE TRIGGER no_account_delete BEFORE DELETE ON accounts BEGIN SELECT RAISE(ABORT, 'account settings are locked'); END")


def verify_odd_lot_account_settings(
    ledger_path: str | Path, account_id: str, result: OddLotResearchResult
) -> bool:
    """Check a research account's archived settings without modifying the archive."""
    uri = Path(ledger_path).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        row = db.execute(
            "SELECT settings_json, settings_sha256 FROM accounts WHERE account_id=?", (account_id,)
        ).fetchone()
    if row is None:
        return False
    settings, digest = row
    return hashlib.sha256(settings.encode()).hexdigest() == digest and settings == _canonical(_account_assumptions(result)).decode()
