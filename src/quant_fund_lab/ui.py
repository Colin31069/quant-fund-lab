from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from quant_fund_lab.analytics import buy_and_hold_equity, metric_frame
from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import MarketData, synthetic_market_data
from quant_fund_lab.data_quality import validate_corporate_actions
from quant_fund_lab.diagnostics import diagnose_walk_forward
from quant_fund_lab.factors import research_factors
from quant_fund_lab.fx import attach_fx_rates, attach_yahoo_fx, validate_fx
from quant_fund_lab.paper import historical_vs_paper_replay
from quant_fund_lab.paper_live import replay_targets_persistently
from quant_fund_lab.provenance import AuditLog, build_run_manifest
from quant_fund_lab.providers import SnapshotProvider, YahooProvider, load_with_failover
from quant_fund_lab.reporting import export_research_report, verify_research_report
from quant_fund_lab.robustness import build_robustness_report
from quant_fund_lab.snapshot import save_market_data_snapshot
from quant_fund_lab.ui_inputs import load_verified_ui_inputs
from quant_fund_lab.walkforward import (
    WalkForwardSpec,
    generate_candidate_grid,
    run_walk_forward,
)

st.set_page_config(page_title="Quant Fund Lab", layout="wide")
st.title("Quant Fund Lab")
st.caption("數學 Alpha → 風險模型 → 組合最佳化 → 模擬成交；僅虛擬資金，不連接券商。")

with st.sidebar:
    st.header("研究設定")
    data_mode = st.selectbox(
        "資料來源",
        ["Yahoo 公開市場資料", "離線合成資料", "M8 Verified Lifecycle Snapshot"],
    )
    verified_mode = data_mode == "M8 Verified Lifecycle Snapshot"
    if verified_mode:
        symbols_text = st.text_input("交易 Security IDs", "")
        benchmark = st.text_input("比較基準 Security ID", "")
        market_snapshot_directory = st.text_input(
            "Market snapshot 目錄", "artifacts/provider_cache/latest"
        )
        lifecycle_snapshot_directory = st.text_input(
            "Lifecycle snapshot 目錄", "artifacts/security_lifecycle/latest"
        )
        st.caption(
            "此模式只接受 stable security_id；兩份 snapshot 都會先做 hash / dataset-ID 驗證。"
        )
    else:
        symbols_text = st.text_input("交易標的", "AAPL,MSFT,NVDA,GOOGL")
        benchmark = st.text_input("比較基準", "SPY")
        market_snapshot_directory = ""
        lifecycle_snapshot_directory = ""
    base_currency = st.selectbox("投資組合基準幣別", ["TWD", "USD"])
    end_date = st.date_input("結束日", value=datetime.now(timezone.utc).date())
    start_date = st.date_input("開始日", value=end_date - timedelta(days=365 * 4))
    initial_cash = st.number_input(
        f"虛擬初始資金（{base_currency}）",
        min_value=10_000.0,
        value=1_000_000.0,
        step=100_000.0,
    )
    execution_price_basis = st.selectbox(
        "成交/持倉價格基準",
        ["adjusted", "raw"],
        index=0,
        help="adjusted 維持總報酬價格；raw 會另行入帳 split/dividend corporate actions。",
    )
    max_weight = st.slider("單一標的最大權重", 0.05, 0.50, 0.25, 0.05)
    rebalance_every = st.slider("再平衡頻率（交易日）", 1, 20, 5)
    train_fraction = st.slider("回測 / paper replay 切分", 0.55, 0.90, 0.70, 0.05)
    run_walkforward = st.checkbox("執行 M2 Walk-forward OOS", value=False)
    walkforward_objective = st.selectbox("Walk-forward 選參指標", ["calmar", "sharpe", "annual_return"])
    st.markdown("**M2-3 風險研究**")
    regime_enabled = st.checkbox("Regime detection", value=True)
    factor_neutralization = st.checkbox("Factor neutralization", value=True)
    factor_neutralization_strength = st.slider(
        "Factor neutralization strength", 0.0, 1.0, 0.50, 0.10
    )
    risk_budget_penalty = st.slider(
        "Risk-budget penalty", 0.0, 0.010, 0.001, 0.001, format="%.3f"
    )
    st.markdown("**M3 Persistent Paper Trading**")
    persist_paper_ledger = st.checkbox("建立本機 persistent paper ledger", value=False)
    st.markdown("**M4 Production Hardening**")
    export_verifiable_report = st.checkbox("匯出可驗證研究報告", value=False)
    st.markdown("**M5 Factor Laboratory**")
    run_factor_research = st.checkbox("執行因子 IC / Decay 研究", value=False)
    enable_factor_alpha = st.checkbox("啟用 trailing-IC Factor Alpha overlay", value=False)
    factor_alpha_weight = st.slider("Factor Alpha overlay 權重", 0.0, 0.60, 0.30, 0.05)
    enable_vol_target = st.checkbox("Volatility targeting", value=False)
    target_annual_volatility = st.slider("目標年化波動", 0.05, 0.30, 0.12, 0.01)
    enable_cvar_control = st.checkbox("CVaR / Expected Shortfall cap", value=False)
    max_daily_cvar = st.slider("最大日 CVaR", 0.005, 0.050, 0.025, 0.005, format="%.3f")
    enable_drawdown_control = st.checkbox("Drawdown de-risking", value=False)
    drawdown_soft_limit = st.slider("Drawdown soft limit", 0.05, 0.20, 0.10, 0.01)
    drawdown_hard_min = min(drawdown_soft_limit + 0.05, 0.40)
    drawdown_hard_limit = st.slider(
        "Drawdown hard limit", drawdown_hard_min, 0.50, max(0.20, drawdown_hard_min), 0.01
    )
    drawdown_min_exposure = st.slider("Hard-limit 最低風險曝險", 0.0, 0.75, 0.25, 0.05)
    run_robustness = st.checkbox("執行 M5-4 Robustness Lab", value=False)
    run = st.button("執行模型", type="primary", use_container_width=True)


@st.cache_data(show_spinner=False)
def load_data(
    mode: str, symbols: tuple[str, ...], start: str, end: str
) -> tuple[MarketData, str, tuple[tuple[str, bool, str | None], ...]]:
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


if run:
    requested_trade_assets = [
        s.strip() if verified_mode else s.strip().upper()
        for s in symbols_text.split(",")
        if s.strip()
    ]
    requested_benchmark = benchmark.strip() if verified_mode else benchmark.strip().upper()
    all_symbols = list(dict.fromkeys(requested_trade_assets + [requested_benchmark]))
    if len(requested_trade_assets) < 2:
        st.error("至少提供兩個交易標的，橫斷面模型才有意義。")
        st.stop()

    try:
        with st.spinner("載入資料並執行 walk-forward paper replay..."):
            source_data_provenance: dict[str, str] = {}
            if verified_mode:
                verified_inputs = load_verified_ui_inputs(
                    market_snapshot_directory,
                    lifecycle_snapshot_directory,
                    requested_trade_assets,
                    requested_benchmark,
                    start=start_date,
                    end=end_date,
                    base_currency=base_currency,
                )
                raw = verified_inputs.raw
                trade_data = verified_inputs.trade_data
                trade_symbols = list(verified_inputs.trade_assets)
                benchmark_symbol = verified_inputs.benchmark_asset
                source_data_provenance = verified_inputs.data_provenance
                data_provider = "verified_identity_snapshots"
                provider_attempts = ((data_provider, True, None),)
            else:
                trade_symbols = requested_trade_assets
                raw, data_provider, provider_attempts = load_data(
                    data_mode,
                    tuple(all_symbols),
                    str(start_date),
                    str(end_date + timedelta(days=1)),
                )
                if data_mode == "Yahoo 公開市場資料":
                    if raw.fx_to_base is None:
                        try:
                            raw = attach_yahoo_fx(raw, base_currency=base_currency)
                        except Exception:  # noqa: BLE001 - retry through verified local fallback.
                            fallback = load_with_failover(
                                [SnapshotProvider(("artifacts/provider_cache",))],
                                all_symbols,
                                str(start_date),
                                str(end_date + timedelta(days=1)),
                            )
                            raw = fallback.data
                            data_provider = fallback.provider
                            provider_attempts = provider_attempts + tuple(
                                (item.provider, item.success, item.error)
                                for item in fallback.attempts
                            )
                    if data_provider == "yahoo":
                        save_market_data_snapshot(
                            raw, "artifacts/provider_cache/latest", overwrite=True
                        )
                else:
                    synthetic_usd_twd = pd.Series(32.0, index=raw.close.index, dtype=float)
                    raw = attach_fx_rates(raw, base_currency, usd_twd=synthetic_usd_twd)
                trade_data = MarketData(
                    open=raw.open[trade_symbols],
                    close=raw.close[trade_symbols],
                    volume=raw.volume[trade_symbols],
                    raw_open=raw.raw_open[trade_symbols] if raw.raw_open is not None else None,
                    raw_close=raw.raw_close[trade_symbols] if raw.raw_close is not None else None,
                    reference=raw.reference[trade_symbols] if raw.reference is not None else None,
                    membership=raw.membership[trade_symbols] if raw.membership is not None else None,
                    terminal_returns=(
                        raw.terminal_returns[trade_symbols]
                        if raw.terminal_returns is not None
                        else None
                    ),
                    dividends=raw.dividends[trade_symbols] if raw.dividends is not None else None,
                    stock_splits=(
                        raw.stock_splits[trade_symbols] if raw.stock_splits is not None else None
                    ),
                    fx_to_base=raw.fx_to_base[trade_symbols] if raw.fx_to_base is not None else None,
                    fx_age_days=(
                        raw.fx_age_days[trade_symbols] if raw.fx_age_days is not None else None
                    ),
                    market_codes=(
                        raw.market_codes[trade_symbols] if raw.market_codes is not None else None
                    ),
                    currency_codes=(
                        raw.currency_codes[trade_symbols]
                        if raw.currency_codes is not None
                        else None
                    ),
                    base_currency=raw.base_currency,
                    exchange=raw.exchange,
                )
                benchmark_symbol = requested_benchmark
            strategy = StrategyConfig(
                max_weight=max_weight,
                rebalance_every=rebalance_every,
                regime_enabled=regime_enabled,
                factor_neutralization=factor_neutralization,
                factor_neutralization_strength=factor_neutralization_strength,
                risk_budget_penalty=risk_budget_penalty,
                factor_alpha_enabled=enable_factor_alpha,
                factor_alpha_weight=factor_alpha_weight,
                volatility_target_enabled=enable_vol_target,
                target_annual_volatility=target_annual_volatility,
                cvar_control_enabled=enable_cvar_control,
                max_daily_cvar=max_daily_cvar,
                drawdown_control_enabled=enable_drawdown_control,
                drawdown_soft_limit=drawdown_soft_limit,
                drawdown_hard_limit=drawdown_hard_limit,
                drawdown_min_exposure=drawdown_min_exposure,
            )
            config = BacktestConfig(
                initial_cash=initial_cash,
                base_currency=base_currency,
                execution_price_basis=execution_price_basis,
                strategy=strategy,
            )
            comparison = historical_vs_paper_replay(trade_data, config, train_fraction=train_fraction)
            robustness = (
                build_robustness_report(
                    trade_data,
                    config,
                    train_fraction,
                    comparison.paper_replay,
                    cost_multipliers=(1.0, 1.5, 2.0),
                    bootstrap_iterations=300,
                    block_length=10,
                    seed=19,
                )
                if run_robustness
                else None
            )
            factor_research = (
                research_factors(
                    trade_data,
                    sampling_every=max(rebalance_every, 1),
                    horizons=(1, 5, 20),
                )
                if run_factor_research
                else None
            )
            action_report = validate_corporate_actions(trade_data)
            fx_report = validate_fx(trade_data, config.max_fx_staleness_days)
            audit = AuditLog("artifacts/audit.jsonl")
            audit.append(
                "DATA_PROVIDER_SELECTED",
                {
                    "provider": data_provider,
                    "attempts": [
                        {"provider": p, "success": ok, "error": error}
                        for p, ok, error in provider_attempts
                    ],
                    "symbols": all_symbols,
                },
            )
            report_export = None
            if export_verifiable_report:
                input_snapshot = save_market_data_snapshot(
                    trade_data, "artifacts/report_input/latest", overwrite=True
                )
                run_context = {
                    "mode": "paper_replay",
                    "train_fraction": float(train_fraction),
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
                report_export = (exported_run.run_id, report_directory, report_verified)
            benchmark_close_base = (
                raw.close[benchmark_symbol] * raw.fx_to_base[benchmark_symbol]
            ).ffill().dropna()
            persistent_nav = None
            persistent_orders = None
            persistent_fills = None
            persistent_positions = None
            persistent_snapshots = None
            persistent_actions = None
            if persist_paper_ledger:
                ledger = replay_targets_persistently(
                    trade_data,
                    comparison.paper_replay.weights,
                    config,
                    "artifacts/paper_trading.sqlite",
                    snapshot_root="artifacts/paper_snapshots",
                    benchmark_close_base=benchmark_close_base,
                    reset=True,
                )
                try:
                    persistent_nav = ledger.nav_history()
                    persistent_orders = ledger.orders()
                    persistent_fills = ledger.fills()
                    persistent_positions = ledger.positions()
                    persistent_snapshots = ledger.snapshots()
                    persistent_actions = ledger.corporate_actions()
                finally:
                    ledger.close()

        st.success(
            f"切分日：{comparison.split_date.date()}；其後區段以重置虛擬資金做 paper replay。"
            f" NAV 基準幣別：{comparison.paper_replay.base_currency}。"
        )
        st.caption(
            f"FX 最大沿用天數：{fx_report.max_age_days:.0f} 日；"
            "換匯只允許使用當日或更早的匯率，不使用未來資料。"
        )
        provider_failed = [name for name, ok, _ in provider_attempts if not ok]
        st.caption(
            f"資料 Provider：{data_provider}。"
            + (f" Failover 前失敗：{', '.join(provider_failed)}。" if provider_failed else "")
        )
        if source_data_provenance:
            st.caption(
                "Verified provenance：market="
                f"{source_data_provenance['market_data_dataset_id'][:12]}…；lifecycle="
                f"{source_data_provenance['security_lifecycle_dataset_id'][:12]}…。"
            )
        if report_export is not None:
            report_run_id, report_path, report_verified = report_export
            st.success(
                f"M4 report 已匯出：{report_path}；run_id={report_run_id}；"
                f"integrity={'PASS' if report_verified else 'FAIL'}。"
            )
        session_reports = comparison.paper_replay.session_validations
        if not session_reports and comparison.paper_replay.session_validation is not None:
            legacy_report = comparison.paper_replay.session_validation
            session_reports = {legacy_report.market: legacy_report}
        if not action_report.is_valid:
            st.warning(
                "企業行動資料有可疑項目："
                f"負股利 {len(action_report.negative_dividend_events)}、"
                f"無效拆股 {len(action_report.invalid_split_events)}、"
                f"拆股後調整報酬異常 {len(action_report.suspicious_split_adjustments)}。"
            )
        for market, session_report in session_reports.items():
            if not (session_report.missing_sessions or session_report.off_calendar_sessions):
                continue
            missing_preview = ", ".join(str(x.date()) for x in session_report.missing_sessions[:3])
            extra_preview = ", ".join(
                str(x.date()) for x in session_report.off_calendar_sessions[:3]
            )
            st.warning(
                f"{market} 市場資料與第三方交易日曆存在差異。"
                f" 日曆有、資料無：{len(session_report.missing_sessions)} 日（{missing_preview or '無'}）；"
                f" 資料有、日曆無：{len(session_report.off_calendar_sessions)} 日（{extra_preview or '無'}）。"
                "可能是臨時休市、日曆版本落差或資料缺口；不自動補造價格。"
            )

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("回測 vs Paper Replay")
            display = comparison.metrics.copy()
            pct_cols = ["total_return", "annual_return", "annual_volatility", "max_drawdown"]
            for c in pct_cols:
                display[c] = display[c].map(lambda x: f"{x:.2%}")
            for c in ["sharpe", "calmar"]:
                display[c] = display[c].map(lambda x: f"{x:.2f}")
            st.dataframe(display, use_container_width=True)

        with col2:
            st.subheader("Paper Replay 與市場基準")
            paper_equity = comparison.paper_replay.equity_curve["equity"]
            benchmark_close = benchmark_close_base.reindex(paper_equity.index).ffill().dropna()
            benchmark_equity = buy_and_hold_equity(benchmark_close, initial_cash)
            comparison_frame = metric_frame({"paper_replay": paper_equity, "benchmark": benchmark_equity})
            st.dataframe(comparison_frame, use_container_width=True)

        fig = go.Figure()
        bt = comparison.backtest.equity_curve["equity"]
        pp = comparison.paper_replay.equity_curve["equity"]
        fig.add_trace(go.Scatter(x=bt.index, y=bt / bt.iloc[0], name="Historical backtest"))
        fig.add_trace(go.Scatter(x=pp.index, y=pp / pp.iloc[0], name="Paper replay"))
        fig.update_layout(title="標準化淨值曲線", yaxis_title="Growth of 1", height=450)
        st.plotly_chart(fig, use_container_width=True)

        if factor_research is not None:
            st.subheader("M5-1 Factor Research")
            if factor_research.summary.empty:
                st.warning("目前資料不足以形成可用的 cross-sectional IC 統計。")
            else:
                st.caption(
                    "IC / Rank IC 使用 factor timestamp 之後的 forward return；"
                    "factor 本身只由當下與更早資料計算。正值代表因子排序方向與未來報酬同向。"
                )
                st.dataframe(factor_research.summary, use_container_width=True, height=360)
                f1, f2 = st.columns(2)
                with f1:
                    st.markdown("**Rank IC Decay**")
                    st.dataframe(factor_research.decay, use_container_width=True, height=300)
                with f2:
                    st.markdown("**Factor Rank Turnover**")
                    st.dataframe(
                        factor_research.turnover.rename("rank_turnover").to_frame(),
                        use_container_width=True,
                        height=300,
                    )
                st.markdown("**Average Cross-sectional Factor Correlation**")
                st.dataframe(
                    factor_research.factor_correlation,
                    use_container_width=True,
                    height=320,
                )

        if enable_factor_alpha:
            st.subheader("M5-2 Learned Factor Alpha")
            learned = comparison.paper_replay.factor_weights
            if learned.empty:
                st.info("尚未累積足夠已實現 IC 樣本；Factor overlay 暫時不改變原始 Alpha。")
            else:
                st.caption(
                    "權重由 signal date 前已完整實現的 Rank IC 學習；5 日 horizon 使用非重疊樣本，"
                    "並以 L1 正規化。正權重代表順向使用，負權重代表反向使用。"
                )
                st.dataframe(learned.tail(40), use_container_width=True, height=320)
            if len(trade_symbols) < 6:
                st.warning("目前股票數少於 6 檔，cross-sectional IC 估計會非常不穩定；較適合研究較大 universe。")

        if enable_vol_target or enable_cvar_control or enable_drawdown_control:
            st.subheader("M5-3 Portfolio Risk Controls")
            controls = comparison.paper_replay.risk_controls
            if controls.empty:
                st.info("目前沒有 risk-control observation。")
            else:
                latest_control = controls.iloc[-1]
                q1, q2, q3, q4 = st.columns(4)
                q1.metric("Final risk scale", f"{float(latest_control['final_scale']):.1%}")
                q2.metric(
                    "Forecast vol after",
                    f"{float(latest_control['forecast_annual_volatility_after']):.1%}",
                )
                q3.metric(
                    "Daily CVaR after",
                    f"{float(latest_control['historical_cvar_after']):.2%}",
                )
                q4.metric("Strategy drawdown", f"{float(latest_control['drawdown']):.1%}")
                st.caption(
                    "Risk-control scale = min(volatility scale, CVaR scale, drawdown scale)，"
                    "只縮小 risky sleeve，剩餘配置為現金，不做槓桿放大。"
                )
                st.dataframe(controls.tail(40), use_container_width=True, height=320)

        st.subheader("M2-3 Regime / Risk Budget")
        regimes = comparison.paper_replay.regimes
        if regimes.empty:
            st.info("目前沒有 regime observation。")
        else:
            latest_regime = regimes.iloc[-1]
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Current regime", str(latest_regime["label"]))
            r2.metric("Trend z", f"{float(latest_regime['trend_z']):.2f}")
            r3.metric("Annualized market vol", f"{float(latest_regime['annual_volatility']):.1%}")
            r4.metric("Gross exposure cap", f"{float(latest_regime['gross_exposure_limit']):.0%}")
            st.caption(
                f"Factor neutralization={'ON' if factor_neutralization else 'OFF'} "
                f"(strength={factor_neutralization_strength:.0%})；"
                f"risk-budget penalty={risk_budget_penalty:.3f}。"
                "Regime 與 factor exposure 每次只使用 signal date 當下以前的資料。"
            )
            st.dataframe(regimes.tail(30), use_container_width=True, height=260)

        if persistent_nav is not None and not persistent_nav.empty:
            st.subheader("M3 Persistent Paper Ledger")
            latest_nav = persistent_nav.iloc[-1]
            open_order_count = int(
                persistent_orders["status"].isin(["NEW", "PARTIAL"]).sum()
                if persistent_orders is not None and not persistent_orders.empty
                else 0
            )
            p1, p2, p3, p4 = st.columns(4)
            p1.metric(
                f"Ledger NAV ({base_currency})",
                f"{float(latest_nav['equity']):,.2f}",
            )
            p2.metric("Realized PnL", f"{float(latest_nav['realized_pnl']):,.2f}")
            p3.metric("Unrealized PnL", f"{float(latest_nav['unrealized_pnl']):,.2f}")
            p4.metric("Open / Partial Orders", str(open_order_count))
            ledger_fig = go.Figure()
            ledger_fig.add_trace(
                go.Scatter(x=persistent_nav.index, y=persistent_nav["equity"], name="Paper ledger NAV")
            )
            if persistent_nav["benchmark_equity"].notna().any():
                ledger_fig.add_trace(
                    go.Scatter(
                        x=persistent_nav.index,
                        y=persistent_nav["benchmark_equity"],
                        name="Benchmark",
                    )
                )
            ledger_fig.update_layout(
                title="Persistent paper NAV vs benchmark",
                yaxis_title=base_currency,
                height=380,
            )
            st.plotly_chart(ledger_fig, use_container_width=True)
            st.caption(
                "SQLite: artifacts/paper_trading.sqlite；每日可重現 market snapshots: "
                "artifacts/paper_snapshots/。未成交數量會保持 NEW/PARTIAL 並在後續交易日重試。"
            )
            pt1, pt2, pt3, pt4, pt5 = st.tabs(
                [
                    "Persistent Orders",
                    "Persistent Fills",
                    "Positions",
                    "Corporate Actions",
                    "Daily Snapshots",
                ]
            )
            with pt1:
                st.dataframe(persistent_orders, use_container_width=True, height=300)
            with pt2:
                st.dataframe(persistent_fills, use_container_width=True, height=300)
            with pt3:
                st.dataframe(persistent_positions, use_container_width=True, height=300)
            with pt4:
                st.dataframe(persistent_actions, use_container_width=True, height=300)
            with pt5:
                st.dataframe(persistent_snapshots, use_container_width=True, height=300)

        if robustness is not None:
            st.subheader("M5-4 Robustness Lab")
            st.caption(
                "Robustness 結果只作診斷，不參與參數選擇：成本壓力固定為 1.0x / 1.5x / 2.0x；"
                "block bootstrap 保留短期報酬相依；regime attribution 只使用當時已知的最新 regime。"
            )
            rb1, rb2, rb3 = st.tabs(
                ["Execution Cost Stress", "Block Bootstrap", "Regime Attribution"]
            )
            with rb1:
                st.dataframe(robustness.cost_stress, use_container_width=True, height=320)
            with rb2:
                st.dataframe(robustness.bootstrap_summary, use_container_width=True, height=320)
            with rb3:
                st.dataframe(robustness.regime_attribution, use_container_width=True, height=320)

        if run_walkforward:
            st.subheader("Walk-forward Out-of-Sample")
            if len(trade_data.close) < 420:
                st.warning("Walk-forward 至少需要約 420 個交易日；目前資料不足。")
            else:
                with st.spinner("執行 walk-forward calibration / OOS test..."):
                    candidates = generate_candidate_grid(
                        strategy,
                        risk_aversion=(2.0, 4.0, 8.0),
                        covariance_shrinkage=(strategy.covariance_shrinkage,),
                        rebalance_every=(5, 10),
                    )
                    wf = run_walk_forward(
                        trade_data,
                        config,
                        candidates,
                        WalkForwardSpec(
                            train_bars=252,
                            validation_bars=84,
                            test_bars=84,
                            step_bars=84,
                            expanding=True,
                            objective=walkforward_objective,
                            max_validation_drawdown=0.35,
                        ),
                    )
                    diagnostics = diagnose_walk_forward(
                        wf,
                        bootstrap_iterations=500,
                        mean_block_length=10.0,
                        seed=11,
                    )
                wf_metrics = pd.DataFrame([wf.oos_metrics], index=["walk_forward_oos"])
                st.dataframe(wf_metrics, use_container_width=True)
                st.dataframe(wf.folds, use_container_width=True, height=300)
                st.markdown("**Multiple-testing / Overfitting diagnostics**")
                d1, d2, d3, d4 = st.columns(4)
                dsr = diagnostics.deflated_sharpe
                reality = diagnostics.reality_check
                d1.metric("Deflated Sharpe 機率", f"{dsr.probability:.1%}")
                d2.metric("OOS Sharpe", f"{dsr.observed_sharpe_annualized:.2f}")
                d3.metric(
                    "Selection-adjusted Sharpe 門檻",
                    f"{dsr.expected_max_sharpe_annualized:.2f}",
                )
                d4.metric("Reality Check p-value", f"{reality.p_value:.3f}")
                st.caption(
                    f"DSR 使用 {dsr.num_trials} 個候選策略的 Validation Sharpe 分布修正 selection bias；"
                    f"Reality Check 對 {reality.candidate_count} 個候選、{reality.sample_size} 個 Validation 報酬"
                    f"做 {reality.bootstrap_iterations} 次 stationary bootstrap。"
                    "這些是研究診斷，不代表未來報酬保證。"
                )
                wf_fig = go.Figure()
                wf_fig.add_trace(
                    go.Scatter(x=wf.oos_equity.index, y=wf.oos_equity, name="OOS equity")
                )
                wf_fig.update_layout(
                    title="Walk-forward 純 OOS 淨值",
                    yaxis_title=f"NAV ({comparison.paper_replay.base_currency})",
                    height=380,
                )
                st.plotly_chart(wf_fig, use_container_width=True)

        tab1, tab2, tab3, tab4 = st.tabs(["成交紀錄", "成本與換手", "目標權重", "Alpha 訊號"])
        with tab1:
            st.dataframe(comparison.paper_replay.fills, use_container_width=True, height=420)
        with tab2:
            costs = comparison.paper_replay.cost_attribution
            if costs.empty:
                st.info("此區段沒有成交，因此沒有交易成本。")
            else:
                c1, c2, c3 = st.columns(3)
                currency = comparison.paper_replay.base_currency
                c1.metric(f"總手續費/稅費（{currency}）", f"{costs['fees'].sum():,.2f}")
                c2.metric(f"估計滑價成本（{currency}）", f"{costs['slippage_cost'].sum():,.2f}")
                c3.metric("累積單向換手", f"{costs['turnover_rate'].sum():.2f}x")
                st.dataframe(costs.tail(50), use_container_width=True, height=360)
        with tab3:
            st.dataframe(comparison.paper_replay.weights.tail(50), use_container_width=True, height=420)
        with tab4:
            st.dataframe(comparison.paper_replay.alphas.tail(50), use_container_width=True, height=420)

    except Exception as exc:  # noqa: BLE001 - UI boundary must surface provider/runtime errors.
        st.exception(exc)
else:
    st.info("設定標的後按「執行模型」。第一次可先選『離線合成資料』驗證整套引擎。")
