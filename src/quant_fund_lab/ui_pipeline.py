"""Data loading, provenance tracking, and persistent execution pipeline for UI."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pandas as pd
import streamlit as st

from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import MarketData, synthetic_market_data
from quant_fund_lab.fx import attach_fx_rates, attach_yahoo_fx
from quant_fund_lab.odd_lot_inputs.prepare import prepare_reviewed_odd_lot_input
from quant_fund_lab.odd_lot_inputs.types import PriceSourcePolicy
from quant_fund_lab.odd_lot_study import PERIODS
from quant_fund_lab.paper_live import replay_targets_persistently
from quant_fund_lab.provenance import AuditLog, build_run_manifest
from quant_fund_lab.providers import SnapshotProvider, YahooProvider, load_with_failover
from quant_fund_lab.reporting import export_research_report, verify_research_report
from quant_fund_lab.snapshot import save_market_data_snapshot
from quant_fund_lab.twse_odd_lot import (
    download_twse_bundle,
    populate_cash_dividends,
    prepare_twse_odd_lot,
)
from quant_fund_lab.twse_preparation import (
    missing_source_manifest,
    summarize_period_issues,
    summarize_quality_issues,
)
from quant_fund_lab.ui_inputs import load_verified_ui_inputs
from quant_fund_lab.ui_sidebar import UIInputs


@dataclass(frozen=True)
class PreparedUIData:
    """Market data bundle and provenance prepared for backtest or odd-lot study."""

    raw: MarketData
    trade_data: MarketData
    trade_symbols: list[str]
    benchmark_symbol: str
    source_data_provenance: dict[str, str]
    data_provider: str
    provider_attempts: tuple
    twse_inputs: object | None = None


@dataclass(frozen=True)
class ReplayedLedgerState:
    """State extracted from persistent paper ledger."""

    persistent_nav: pd.DataFrame | None
    persistent_orders: pd.DataFrame | None
    persistent_fills: pd.DataFrame | None
    persistent_positions: pd.DataFrame | None
    persistent_snapshots: pd.DataFrame | None
    persistent_actions: pd.DataFrame | None
    persistent_receivables: pd.DataFrame | None
    persistent_interest_credits: pd.DataFrame | None
    persistent_session_commits: pd.DataFrame | None
    persistent_replay_execution_config: dict | None
    persistent_ledger_audit: object | None


@st.cache_data(show_spinner=False)
def load_data(
    mode: str, symbols: tuple[str, ...], start: str, end: str
) -> tuple[MarketData, str, tuple[tuple[str, bool, str | None], ...]]:
    """Cached loader with failover across Yahoo and local snapshots."""
    if mode == "離線合成資料":
        return synthetic_market_data(symbols=symbols, periods=800), "synthetic", (("synthetic", True, None),)
    result = load_with_failover(
        [YahooProvider(), SnapshotProvider(("artifacts/provider_cache",))],
        list(symbols),
        start,
        end,
    )
    attempts = tuple((item.provider, item.success, item.error) for item in result.attempts)
    return result.data, result.provider, attempts


def prepare_ui_market_data(
    inputs: UIInputs,
    all_symbols: list[str],
    requested_trade_assets: list[str],
    requested_benchmark: str,
) -> PreparedUIData:
    """Load, align, and validate market data according to user source selection."""
    if inputs.twse_mode:
        warmup_start = inputs.start_date - timedelta(days=250)
        if inputs.twse_download:
            download_twse_bundle(
                inputs.twse_directory,
                all_symbols,
                str(warmup_start),
                str(inputs.end_date),
                authorized=inputs.twse_authorized,
            )
        if inputs.twse_cash_events:
            populate_cash_dividends(inputs.twse_directory, all_symbols)
        if inputs.reviewed_mode:
            policy = PriceSourcePolicy(
                str(warmup_start),
                str(inputs.end_date),
                str(inputs.end_date),
                policy_id="reviewed_provider_v2" if inputs.reviewed_no_quote else "reviewed_provider_v1",
                schema_version=2 if inputs.reviewed_no_quote else 1,
            )
            twse_inputs = prepare_reviewed_odd_lot_input(
                inputs.twse_directory, inputs.provider_directory, all_symbols, policy
            ).evidence
        else:
            twse_inputs = prepare_twse_odd_lot(
                inputs.twse_directory, all_symbols, str(warmup_start), str(inputs.end_date)
            )
        raw = twse_inputs.data
        trade_data = raw
        trade_symbols = requested_trade_assets
        benchmark_symbol = requested_benchmark
        source_data_provenance = twse_inputs.provenance
        data_provider = "provider_reviewed" if inputs.reviewed_mode else "twse_official"
        provider_attempts = ((data_provider, True, None),)
        if twse_inputs.issues:
            st.warning(f"官方資料檢查發現 {len(twse_inputs.issues)} 項問題；受影響期間不計算績效。")
            summary, details = summarize_quality_issues(twse_inputs.issues, symbols=raw.symbols)
            period_quality = summarize_period_issues(
                twse_inputs.issues,
                raw.close.index,
                PERIODS,
                warmup=max(120, StrategyConfig().warmup_days),
                coverage_end=twse_inputs.provenance["coverage_end"],
            )
            st.caption("各期暖機起點依目前觀測值估計，缺失交易日可能改變估計；正式守門仍以研究結果為準。")
            st.dataframe(period_quality, use_container_width=True)
            st.dataframe(summary, use_container_width=True)
            checklist = missing_source_manifest(twse_inputs.issues)
            if not checklist.empty:
                st.caption("缺檔清單的網址僅供核對；填入本機檔案及實際來源網址後才可匯入。")
                st.download_button(
                    "下載缺檔匯入清單",
                    checklist.to_csv(index=False).encode("utf-8-sig"),
                    file_name="twse_missing_sources.csv",
                    mime="text/csv",
                )
            with st.expander("完整資料問題與關聯"):
                st.dataframe(details, use_container_width=True)
        else:
            st.success("資料包檢查通過；歷史發布與修訂時間仍未獨立驗證。")
        return PreparedUIData(
            raw=raw,
            trade_data=trade_data,
            trade_symbols=trade_symbols,
            benchmark_symbol=benchmark_symbol,
            source_data_provenance=source_data_provenance,
            data_provider=data_provider,
            provider_attempts=provider_attempts,
            twse_inputs=twse_inputs,
        )

    if inputs.verified_mode:
        verified_inputs = load_verified_ui_inputs(
            inputs.market_snapshot_directory,
            inputs.lifecycle_snapshot_directory,
            requested_trade_assets,
            requested_benchmark,
            cash_in_lieu_snapshot_directory=inputs.cash_in_lieu_snapshot_directory or None,
            start=inputs.start_date,
            end=inputs.end_date,
            base_currency=inputs.base_currency,
        )
        return PreparedUIData(
            raw=verified_inputs.raw,
            trade_data=verified_inputs.trade_data,
            trade_symbols=list(verified_inputs.trade_assets),
            benchmark_symbol=verified_inputs.benchmark_asset,
            source_data_provenance=verified_inputs.data_provenance,
            data_provider="verified_identity_snapshots",
            provider_attempts=(("verified_identity_snapshots", True, None),),
        )

    trade_symbols = requested_trade_assets
    raw, data_provider, provider_attempts = load_data(
        inputs.data_mode,
        tuple(all_symbols),
        str(inputs.start_date),
        str(inputs.end_date + timedelta(days=1)),
    )
    if inputs.data_mode == "Yahoo 公開市場資料":
        if raw.fx_to_base is None:
            try:
                raw = attach_yahoo_fx(raw, base_currency=inputs.base_currency)
            except Exception:  # noqa: BLE001 - retry through verified local fallback.
                fallback = load_with_failover(
                    [SnapshotProvider(("artifacts/provider_cache",))],
                    all_symbols,
                    str(inputs.start_date),
                    str(inputs.end_date + timedelta(days=1)),
                )
                raw = fallback.data
                data_provider = fallback.provider
                provider_attempts = provider_attempts + tuple(
                    (item.provider, item.success, item.error) for item in fallback.attempts
                )
        if data_provider == "yahoo":
            save_market_data_snapshot(
                raw, "artifacts/provider_cache/latest", overwrite=True
            )
    else:
        synthetic_usd_twd = pd.Series(32.0, index=raw.close.index, dtype=float)
        raw = attach_fx_rates(raw, inputs.base_currency, usd_twd=synthetic_usd_twd)

    trade_data = MarketData(
        open=raw.open[trade_symbols],
        close=raw.close[trade_symbols],
        volume=raw.volume[trade_symbols],
        raw_open=raw.raw_open[trade_symbols] if raw.raw_open is not None else None,
        raw_close=raw.raw_close[trade_symbols] if raw.raw_close is not None else None,
        reference=raw.reference[trade_symbols] if raw.reference is not None else None,
        membership=raw.membership[trade_symbols] if raw.membership is not None else None,
        terminal_returns=(
            raw.terminal_returns[trade_symbols] if raw.terminal_returns is not None else None
        ),
        dividends=raw.dividends[trade_symbols] if raw.dividends is not None else None,
        stock_splits=(
            raw.stock_splits[trade_symbols] if raw.stock_splits is not None else None
        ),
        cash_in_lieu_prices=(
            raw.cash_in_lieu_prices[trade_symbols]
            if raw.cash_in_lieu_prices is not None
            else None
        ),
        cash_in_lieu_settlement_dates=(
            raw.cash_in_lieu_settlement_dates[trade_symbols]
            if raw.cash_in_lieu_settlement_dates is not None
            else None
        ),
        fx_to_base=raw.fx_to_base[trade_symbols] if raw.fx_to_base is not None else None,
        fx_age_days=(
            raw.fx_age_days[trade_symbols] if raw.fx_age_days is not None else None
        ),
        market_codes=(
            raw.market_codes[trade_symbols] if raw.market_codes is not None else None
        ),
        currency_codes=(
            raw.currency_codes[trade_symbols] if raw.currency_codes is not None else None
        ),
        base_currency=raw.base_currency,
        exchange=raw.exchange,
    )
    return PreparedUIData(
        raw=raw,
        trade_data=trade_data,
        trade_symbols=trade_symbols,
        benchmark_symbol=requested_benchmark,
        source_data_provenance={},
        data_provider=data_provider,
        provider_attempts=provider_attempts,
    )


def export_ui_report_if_requested(
    inputs: UIInputs,
    comparison: object,
    trade_data: MarketData,
    config: BacktestConfig,
    source_data_provenance: dict[str, str],
    audit: AuditLog,
) -> tuple[str, str, bool] | None:
    """Export verifiable M4 research report if user opted in."""
    if not inputs.export_verifiable_report:
        return None
    input_snapshot = save_market_data_snapshot(
        trade_data, "artifacts/report_input/latest", overwrite=True
    )
    run_context = {
        "mode": "paper_replay",
        "train_fraction": float(inputs.train_fraction),
        "split_date": str(comparison.split_date.date()),
    }
    data_provenance = dict(source_data_provenance)
    if data_provenance:
        data_provenance["derived_trade_dataset_id"] = input_snapshot.dataset_id
    else:
        data_provenance["market_data_dataset_id"] = input_snapshot.dataset_id
    run_manifest = build_run_manifest(
        config,
        input_snapshot.dataset_id,
        run_context=run_context,
        data_provenance=data_provenance,
    )
    report_directory = f"artifacts/reports/{run_manifest.run_id}"
    exported_run, _ = export_research_report(
        comparison.paper_replay,
        config,
        input_snapshot.dataset_id,
        report_directory,
        run_context=run_context,
        data_provenance=data_provenance,
    )
    report_verified = verify_research_report(report_directory)
    audit.append(
        "REPORT_EXPORTED",
        {
            "run_id": exported_run.run_id,
            "dataset_id": input_snapshot.dataset_id,
            "data_provenance": data_provenance,
            "path": report_directory,
            "verified": report_verified,
        },
    )
    return exported_run.run_id, report_directory, report_verified


def run_ui_persistent_ledger(
    inputs: UIInputs,
    trade_data: MarketData,
    weights: pd.DataFrame,
    config: BacktestConfig,
    benchmark_close_base: pd.Series,
    paper_ledger_reset: bool,
) -> ReplayedLedgerState:
    """Execute persistent ledger replay and extract state."""
    ledger = replay_targets_persistently(
        trade_data,
        weights,
        config,
        inputs.paper_ledger_path,
        snapshot_root=inputs.paper_snapshot_root,
        benchmark_close_base=benchmark_close_base,
        reset=paper_ledger_reset,
    )
    try:
        return ReplayedLedgerState(
            persistent_nav=ledger.nav_history(),
            persistent_orders=ledger.orders(),
            persistent_fills=ledger.fills(),
            persistent_positions=ledger.positions(),
            persistent_snapshots=ledger.snapshots(),
            persistent_actions=ledger.corporate_actions(),
            persistent_receivables=ledger.cash_in_lieu_receivables(),
            persistent_interest_credits=ledger.cash_interest_credits(),
            persistent_session_commits=ledger.session_commits(),
            persistent_replay_execution_config=ledger.replay_execution_config(),
            persistent_ledger_audit=ledger.audit_integrity(),
        )
    finally:
        ledger.close()
