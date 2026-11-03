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
from .odd_lot_diagnostics.types import StudyRiskDiagnostics
from .odd_lot_execution import validate_instrument_rules
from .odd_lot_inputs.reporting import price_selection_csv, verify_price_selection_report
from .odd_lot_research import (
    OddLotResearchConfig,
    OddLotResearchResult,
    run_odd_lot_research,
    validate_raw_split_basis,
)
from .odd_lot_sensitivity.types import MatchedSensitivity
from .snapshot import load_market_data_snapshot, save_market_data_snapshot
from .twse_preparation import (
    missing_source_manifest,
    summarize_period_issues,
    summarize_quality_issues,
)
from .twse_quality.frozen import (
    assess_frozen_inputs,
    explicit_periods,
    reconstruct_reviewed_inputs,
    validate_frozen_readiness,
)
from .twse_quality.types import READINESS_RULE_VERSION

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
    readiness_fingerprint: str | None = None
    benchmark_specs: dict[str, dict] | None = None
    risk_diagnostics: StudyRiskDiagnostics | None = None
    matched_sensitivity: MatchedSensitivity | None = None


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
    source_files: dict[str, Path] | None = None,
    source_hashes: dict[str, str] | None = None,
    quality_issues: list[dict[str, str]] | None = None,
) -> Path:
    """Freeze source bytes and all assumptions before running an experiment.

    Existing studies are verified and reused, never overwritten.
    """
    research = research or OddLotResearchConfig()
    base_config = base_config or BacktestConfig(initial_cash=100_000.0, base_currency="TWD")
    if source == "twse_official" and (source_provenance or {}).get("source_policy"):
        raise ValueError("reviewed provider inputs require their own source identity")
    if source in {"twse_official", "provider_reviewed"} and (
        not source_files or source_hashes is None or quality_issues is None
        or not source_provenance or "coverage_end" not in source_provenance
    ):
        raise ValueError("TWSE studies require source files, provenance and a quality report")
    symbols = tuple(dict.fromkeys(symbols))
    if len(symbols) < 2 or benchmark in symbols:
        raise ValueError("study requires at least two distinct trade assets and a separate benchmark")
    validate_instrument_rules(list(symbols), research.instrument_rules)
    data = _subset(data, [*symbols, benchmark])
    if data.close.index.has_duplicates or not data.close.index.is_monotonic_increasing:
        raise ValueError("study dates must be unique and chronological")
    parent = Path(root)
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".study-", dir=parent) as temporary:
        staging = Path(temporary) / "payload"
        snapshot = save_market_data_snapshot(data, staging / "snapshot")
        archived_sources: dict[str, str] = {}
        for name, path in sorted((source_files or {}).items()):
            relative = Path(name)
            if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                raise ValueError(f"unsafe source file path: {name}")
            raw = Path(path).read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if source_hashes is None or source_hashes.get(name) != digest:
                raise ValueError(f"source file changed during study preparation: {name}")
            target = staging / "sources" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            archived_sources[name] = digest
        if source_hashes is not None and set(source_hashes) != set(archived_sources):
            raise ValueError("source file inventory changed during study preparation")
        payload = {
            "schema_version": 2,
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
            "execution_assumption": "daily_limit_order_ordinary_open_proxy_v2",
            "settlement_assumption": "observed_market_sessions_as_t_plus_2_proxy_credit_after_open",
            "survivorship_warning": "fixed contemporary sample, not a point-in-time universe",
        }
        if source_files is not None:
            payload["source_files"] = archived_sources
            payload["quality_issues"] = list(quality_issues or [])
        if source in {"twse_official", "provider_reviewed"}:
            payload["schema_version"] = 3
            payload["periods"] = explicit_periods(PERIODS, source_provenance["coverage_end"])
            readiness = assess_frozen_inputs(data, payload, staging)
            payload["readiness"] = readiness.to_dict()
            payload["readiness_fingerprint"] = readiness.readiness_fingerprint
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
    if metadata.get("schema_version") not in {1, 2, 3}:
        raise ValueError("unsupported frozen study schema")
    if metadata.get("data_source") == "provider_reviewed" and metadata["schema_version"] != 3:
        raise ValueError("reviewed provider studies require the shared readiness schema")
    study_id = metadata.get("study_id")
    payload = {key: value for key, value in metadata.items() if key != "study_id"}
    if study_id != hashlib.sha256(_canonical(payload)).hexdigest()[:24]:
        raise ValueError("study configuration integrity check failed")
    for name, expected in metadata.get("source_files", {}).items():
        relative = Path(name)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise ValueError("unsafe frozen source path")
        path = root / "sources" / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"study source integrity check failed: {name}")
    data = load_market_data_snapshot(root / "snapshot")
    snapshot_manifest = json.loads((root / "snapshot" / "manifest.json").read_text(encoding="utf-8"))
    if snapshot_manifest["dataset_id"] != metadata["dataset_id"]:
        raise ValueError("study snapshot identity mismatch")
    if data.symbols != metadata["symbols"] + [metadata["benchmark"]]:
        raise ValueError("study snapshot symbols conflict with frozen configuration")
    if snapshot_manifest["start"] != str(data.close.index.min().date()) or snapshot_manifest["end"] != str(data.close.index.max().date()):
        raise ValueError("study snapshot date range conflicts with its manifest")
    validate_frozen_readiness(data, metadata, root)
    return data, metadata


def _backtest_config(payload: dict) -> BacktestConfig:
    values = dict(payload)
    values["strategy"] = StrategyConfig(**values["strategy"])
    values["us_costs"] = MarketCostConfig(**values["us_costs"])
    values["tw_costs"] = MarketCostConfig(**values["tw_costs"])
    values["dividend_withholding"] = DividendWithholdingConfig(**values["dividend_withholding"])
    return BacktestConfig(**values)


def run_frozen_odd_lot_study(directory: str | Path, *, _include_sensitivity: bool = True) -> OddLotStudyResult:
    if type(_include_sensitivity) is not bool:
        raise TypeError("sensitivity execution flag must be boolean")
    data, metadata = load_frozen_odd_lot_study(directory)
    if metadata["package_version"] != __version__:
        raise ValueError("study was frozen with a different package version; freeze a new study")
    if metadata["data_source"] not in {"twse_official", "provider_reviewed", "synthetic"}:
        raise ValueError("odd-lot studies require a quality-reviewed TWSE bundle or explicitly synthetic data")
    if (metadata.get("schema_version") == 3
            and metadata["readiness"]["rule_version"] != READINESS_RULE_VERSION):
        raise ValueError("study used older readiness rules; preserve it and freeze a new study")
    trade_data = _subset(data, metadata["symbols"])
    base = _backtest_config(metadata["backtest_config"])
    research = OddLotResearchConfig(**metadata["research_config"])
    results: dict[tuple[str, str], OddLotResearchResult] = {}
    rows: list[dict] = []
    unavailable: dict[str, str] = {}
    period_data: dict[str, MarketData] = {}
    for period, (start, end) in metadata["periods"].items():
        selected_data = trade_data
        selected_all = data
        if metadata["data_source"] in {"twse_official", "provider_reviewed"}:
            # Every reported period must have a complete 120-session warm-up.
            if metadata.get("schema_version") == 3:
                decision = next(p for p in metadata["readiness"]["periods"] if p["period"] == period)
                if decision["status"] != "ready":
                    blocked = set(decision["blocking_ids"])
                    details = [f["detail"] for f in metadata["readiness"]["findings"]
                               if f["finding_id"] in blocked]
                    reason = "; ".join(details[:20])
                    if len(details) > 20:
                        reason += f"；另有 {len(details) - 20} 項，完整紀錄見正式修復清單"
                    for strategy in ("ensemble", "momentum", "equal_weight", "benchmark"):
                        unavailable[f"{period}/{strategy}"] = reason
                    continue
            start_ts = pd.Timestamp(start)
            end_ts = pd.Timestamp(end) if end else data.close.index.max()
            first_pos = int(data.close.index.searchsorted(start_ts, side="left"))
            warmup = max(120, base.strategy.warmup_days)
            reason = ""
            if first_pos < warmup:
                reason = f"{start} 前不足 {warmup} 個交易日暖機資料"
            elif end and pd.Timestamp(metadata["source_provenance"]["coverage_end"]) < end_ts:
                reason = f"資料未涵蓋 {end} 結束的研究期間"
            if first_pos >= len(data.close.index) or end_ts < start_ts:
                reason = "研究期間缺少交易日"
            if not reason:
                window_start = data.close.index[first_pos - warmup]
                conflicts = [issue for issue in metadata.get("quality_issues", [])
                             if pd.Timestamp(issue["start"]) <= end_ts
                             and pd.Timestamp(issue["end"]) >= window_start]
                if conflicts:
                    reason = "; ".join(f"{i['symbol']} {i['start']}–{i['end']}: {i['detail']}" for i in conflicts[:20])
                    if len(conflicts) > 20:
                        reason += f"；另有 {len(conflicts) - 20} 項資料問題"
            if reason:
                for strategy in ("ensemble", "momentum", "equal_weight"):
                    unavailable[f"{period}/{strategy}"] = reason
                unavailable[f"{period}/benchmark"] = reason
                continue
            from .twse_odd_lot import _total_return
            selected_all = data.slice(start=window_start, end=end_ts)
            adjusted = _total_return(selected_all.raw_close, selected_all.dividends, selected_all.stock_splits)
            selected_all = replace(selected_all, close=adjusted,
                                   open=selected_all.raw_open * adjusted.div(selected_all.raw_close),
                                   reference=adjusted.shift(1))
            validate_raw_split_basis(selected_all)
            selected_data = _subset(selected_all, metadata["symbols"])
        period_data[period] = selected_data
        for strategy in ("ensemble", "momentum", "equal_weight"):
            try:
                result = run_odd_lot_research(selected_data, replace(research, strategy=strategy), base, start=start, end=end)
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
            benchmark = selected_all.close[metadata["benchmark"]].reindex(index).ffill().dropna()
            if len(benchmark) >= 2 and benchmark.index[0] == index[0]:
                curve = buy_and_hold_equity(benchmark, base.initial_cash)
                rows.append({"period": period, "strategy": f"{metadata['benchmark']}_total_return_proxy_no_trading_costs", **performance_metrics(curve)})
            else:
                unavailable[f"{period}/benchmark"] = "benchmark lacks an observation at the interval start"

    sensitivity: list[dict] = []
    start, end = metadata["periods"]["validation"]
    for strategy in (("ensemble", "momentum") if _include_sensitivity else ()):
        if ("validation", strategy) not in results:
            continue
        scenarios = list(dict.fromkeys((
            (0.0, 5.0, research.fill_fraction), (20.0, 5.0, research.fill_fraction),
            (50.0, 5.0, research.fill_fraction), (20.0, 10.0, research.fill_fraction),
            (research.min_commission, research.slippage_bps, 0.25),
            (research.min_commission, research.slippage_bps, 0.50),
            (research.min_commission, research.slippage_bps, 1.00),
        )))
        for commission, slippage, fraction in scenarios:
            scenario = replace(research, strategy=strategy, min_commission=commission,
                               slippage_bps=slippage, fill_fraction=fraction)
            if scenario == results[("validation", strategy)].config:
                result = results[("validation", strategy)]
            else:
                result = run_odd_lot_research(period_data["validation"], scenario, base, start=start, end=end)
            sensitivity.append({"strategy": strategy, "min_commission": commission,
                                "slippage_bps": slippage, "fill_fraction": fraction,
                                **result.metrics, **result.trade_summary})
    return OddLotStudyResult(
        study_id=metadata["study_id"], dataset_id=metadata["dataset_id"],
        comparison=pd.DataFrame(rows), sensitivity=pd.DataFrame(sensitivity),
        results=results, unavailable=unavailable,
        holdout_untouched=metadata["holdout_untouched"],
        readiness_fingerprint=metadata.get("readiness_fingerprint"),
    )


def export_odd_lot_study_report(directory: str | Path, study: OddLotStudyResult) -> Path:
    """Write a new, hashed report without overwriting another run."""
    root = Path(directory)
    data, metadata = load_frozen_odd_lot_study(root)
    if study.study_id != metadata["study_id"] or study.dataset_id != metadata["dataset_id"]:
        raise ValueError("study results do not match the frozen input")
    if study.readiness_fingerprint != metadata.get("readiness_fingerprint"):
        raise ValueError("study results do not match frozen readiness")
    target = root / "reports" / uuid.uuid4().hex
    target.mkdir(parents=True, exist_ok=False)
    _write_account_archive(target / "study_ledger.sqlite", study)
    study.comparison.to_csv(target / "comparison.csv", index=False)
    study.sensitivity.to_csv(target / "sensitivity.csv", index=False)
    if study.benchmark_specs is not None:
        (target / "benchmark_specs.json").write_text(
            json.dumps(study.benchmark_specs, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
    if metadata["data_source"] == "provider_reviewed":
        selected = reconstruct_reviewed_inputs(metadata, root).selection
        (target / "price_selection.csv").write_bytes(price_selection_csv(selected))
    if "action_date_reviews.csv" in metadata.get("source_files", {}):
        (target / "action_date_reviews.csv").write_bytes(
            (root / "sources" / "action_date_reviews.csv").read_bytes()
        )
    execution_rows = []
    for (period, strategy), result in study.results.items():
        order_status = result.orders.get("status", pd.Series(dtype=str))
        last = result.equity_curve.iloc[-1]
        execution_rows.append({"period": period, "strategy": strategy, "orders": len(order_status),
                               "filled_orders": int(order_status.eq("filled").sum()),
                               "partial_expired_orders": int(order_status.eq("partial_expired").sum()),
                               "expired_orders": int(order_status.eq("expired").sum()),
                               "commission": float(result.fills.get("commission", pd.Series(dtype=float)).sum()),
                               "sell_tax": float(result.fills.get("sell_tax", pd.Series(dtype=float)).sum()),
                               "slippage_cost": float(result.fills.get("slippage_cost", pd.Series(dtype=float)).sum()),
                               "available_cash": last["cash"], "buy_payables": last["buy_payables"],
                               "sale_receivables": last["sale_receivables"],
                               "sale_payables": last["sale_payables"]})
    execution_summary = pd.DataFrame(execution_rows)
    execution_summary.to_csv(target / "execution_summary.csv", index=False)
    diagnostic_html = ""
    if study.risk_diagnostics is not None:
        from .odd_lot_protocol.diagnostics import export_risk_diagnostics

        diagnostic_html = export_risk_diagnostics(target, study.risk_diagnostics)
    if study.matched_sensitivity is not None:
        from .odd_lot_sensitivity.reporting import export_matched_sensitivity

        diagnostic_html += export_matched_sensitivity(target, study.matched_sensitivity)
    readiness_repairs_html = ""
    quality = pd.DataFrame(metadata.get("quality_issues", []), columns=["start", "end", "symbol", "detail"])
    quality.to_csv(target / "quality_issues.csv", index=False)
    if metadata.get("schema_version") == 3:
        (target / "readiness.json").write_text(
            json.dumps(metadata["readiness"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        pd.DataFrame(metadata["readiness"]["periods"]).to_csv(target / "readiness_periods.csv", index=False)
        from .twse_quality.repairs import export_repair_summary

        readiness_repairs_html = export_repair_summary(target, metadata["readiness"])
    summary, grouped_quality = summarize_quality_issues(metadata.get("quality_issues", []), symbols=data.symbols)
    period_quality = summarize_period_issues(
        metadata.get("quality_issues", []), data.close.index, metadata["periods"],
        warmup=max(120, _backtest_config(metadata["backtest_config"]).strategy.warmup_days),
        coverage_end=metadata.get("source_provenance", {}).get("coverage_end"),
    )
    summary.to_csv(target / "quality_summary.csv", index=False)
    grouped_quality.to_csv(target / "quality_grouped.csv", index=False)
    period_quality.to_csv(target / "quality_periods.csv", index=False)
    missing_source_manifest(metadata.get("quality_issues", [])).to_csv(target / "missing_source_manifest.csv", index=False)
    (target / "assumptions.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (target / "unavailable.json").write_text(json.dumps(study.unavailable, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (target / "report.html").write_text(
        "<!doctype html><html><head><meta charset='utf-8'><title>Odd-lot research</title>"
        "<style>body{font-family:system-ui;margin:2em}table{border-collapse:collapse}"
        "th,td{padding:.4em;border:1px solid #ccc}</style></head><body>"
        "<h1>台股零股研究</h1><p>模擬資料、普通交易開盤代理價格與歷史成交量代理；"
        "成交比例、限價和成本為情境假設，不保證實際零股成交或止損。"
        "以資料交易日作 T+2 交割日代理，未確認交割日曆或券商可用資金規則；"
        "固定現存股票池有存活者偏差；"
        "股利與股票股利在除權息日模擬入帳，歷史資料修訂及發布時間未獨立驗證。</p>"
        + ("<p>資料來源為 TWSE 與 FinMind，各筆價格的原始來源見 price_selection.csv；"
           "事件與交易日曆另依官方佐證核對。</p>" if metadata["data_source"] == "provider_reviewed" else "") +
        ("<p>2025 年後的歷史評估為探索性，未證實為獨立樣本外結果。</p>" if not study.holdout_untouched else "") +
        ("<p>必要資料尚未通過檢查，沒有可報告的績效。</p>" if study.comparison.empty else "") +
        ("<h2>可交易 ETF 基準</h2><p>期初單次零股委託，未成交量當日到期；"
         "不套止損、不補單，股利保留現金。採相同成本與交割代理，ETF 稅率／限價規則另行明列。"
         "無成本總報酬參考與可交易基準分列，不以不同成本口徑直接排名。</p>"
         + pd.DataFrame(study.benchmark_specs).T.to_html(index=False, escape=True)
         if study.benchmark_specs is not None else "") +
        ("<p>經佐證核對的現金股利日期修訂見 action_date_reviews.csv；"
         "原訂日期保留，模擬入帳使用核對後的有效交易日。</p>"
         if "action_date_reviews.csv" in metadata.get("source_files", {}) else "") +
        ("<h2>正式就緒判定</h2><p>" + study.readiness_fingerprint + "</p>" +
         pd.DataFrame(metadata["readiness"]["periods"])[["period", "start", "end", "status"]].to_html(index=False)
         if study.readiness_fingerprint else "") +
        readiness_repairs_html +
        "<h2>分段比較</h2>" + study.comparison.to_html(index=False) +
        "<h2>成本敏感度（驗證期）</h2>" + study.sensitivity.to_html(index=False) +
        "<h2>委託與交割摘要</h2>" + execution_summary.to_html(index=False) +
        diagnostic_html +
        "<h2>不可用區段及原因</h2>" + pd.DataFrame([{"period": k, "reason": v} for k, v in study.unavailable.items()]).to_html(index=False, escape=True) +
        "<h2>各區段資料問題</h2><p>暖機起點依目前已有觀測值估計；缺失交易日可能使估計改變，不代表資料完整。</p>" + period_quality.to_html(index=False, escape=True) +
        "<h2>資料問題分類</h2>" + summary.to_html(index=False, escape=True) +
        "<h2>資料品質問題明細</h2>" + quality.to_html(index=False, escape=True) +
        "</body></html>", encoding="utf-8"
    )
    for (period, strategy), result in study.results.items():
        prefix = f"{period}_{strategy}"
        for name in ("equity_curve", "fills", "orders", "settlements", "signals", "episodes", "corporate_actions", "terminal_events"):
            getattr(result, name).to_csv(target / f"{prefix}_{name}.csv", index=name == "equity_curve")
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(target.iterdir()) if path.is_file()}
    manifest = {"study_id": study.study_id, "dataset_id": study.dataset_id, "files": hashes}
    if readiness_repairs_html:
        from .twse_quality.repairs import REPAIR_SUMMARY_RULE

        manifest["repair_summary_rule"] = REPAIR_SUMMARY_RULE
    manifest["report_id"] = hashlib.sha256(_canonical(manifest)).hexdigest()
    (target / "report_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return target


def verify_odd_lot_study_report(directory: str | Path) -> bool:
    root = Path(directory)
    try:
        manifest = json.loads((root / "report_manifest.json").read_text(encoding="utf-8"))
        report_id = manifest.pop("report_id")
        _, metadata = load_frozen_odd_lot_study(root.parent.parent)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return False
    if hashlib.sha256(_canonical(manifest)).hexdigest() != report_id:
        return False
    if manifest.get("study_id") != metadata["study_id"] or manifest.get("dataset_id") != metadata["dataset_id"]:
        return False
    if not all((root / name).is_file() and hashlib.sha256((root / name).read_bytes()).hexdigest() == expected for name, expected in manifest["files"].items()):
        return False
    from .twse_quality.repairs import verify_repair_summary

    if not verify_repair_summary(root, metadata, manifest):
        return False
    if metadata["data_source"] == "provider_reviewed":
        try:
            selected = reconstruct_reviewed_inputs(metadata, root.parent.parent).selection
            if not verify_price_selection_report(root, selected, manifest):
                return False
        except (OSError, ValueError, TypeError, KeyError):
            return False
    protocol_files = ("protocol.json", "experiment.json")
    if any((root / name).exists() or name in manifest["files"] for name in protocol_files):
        if not all(name in manifest["files"] for name in protocol_files):
            return False
        try:
            from .odd_lot_protocol.report_binding import verify_protocol_report_binding

            verify_protocol_report_binding(root, metadata)
        except (OSError, ValueError, TypeError, KeyError):
            return False
    return True


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
            for name in ("equity_curve", "fills", "orders", "settlements", "signals", "episodes", "corporate_actions", "terminal_events"):
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
