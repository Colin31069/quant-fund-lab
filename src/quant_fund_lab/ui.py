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
from quant_fund_lab.snapshot import save_market_data_snapshot
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
    data_mode = st.selectbox("資料來源", ["Yahoo 公開市場資料", "離線合成資料"])
    symbols_text = st.text_input("交易標的", "AAPL,MSFT,NVDA,GOOGL")
    benchmark = st.text_input("比較基準", "SPY")
    base_currency = st.selectbox("投資組合基準幣別", ["TWD", "USD"])
    end_date = st.date_input("結束日", value=datetime.now(timezone.utc).date())
    start_date = st.date_input("開始日", value=end_date - timedelta(days=365 * 4))
    initial_cash = st.number_input(
        f"虛擬初始資金（{base_currency}）",
        min_value=10_000.0,
        value=1_000_000.0,
        step=100_000.0,
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
    trade_symbols = [s.strip().upper() for s in symbols_text.split(",") if s.strip()]
    all_symbols = list(dict.fromkeys(trade_symbols + [benchmark.strip().upper()]))
    if len(trade_symbols) < 2:
        st.error("至少提供兩個交易標的，橫斷面模型才有意義。")
        st.stop()

    try:
        with st.spinner("載入資料並執行 walk-forward paper replay..."):
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
                            (item.provider, item.success, item.error) for item in fallback.attempts
                        )
                if data_provider == "yahoo":
                    save_market_data_snapshot(raw, "artifacts/provider_cache/latest", overwrite=True)
            else:
                synthetic_usd_twd = pd.Series(32.0, index=raw.close.index, dtype=float)
                raw = attach_fx_rates(raw, base_currency, usd_twd=synthetic_usd_twd)
            trade_data = MarketData(
                open=raw.open[trade_symbols],
                close=raw.close[trade_symbols],
                volume=raw.volume[trade_symbols],
                reference=raw.reference[trade_symbols] if raw.reference is not None else None,
                membership=raw.membership[trade_symbols] if raw.membership is not None else None,
                terminal_returns=(
                    raw.terminal_returns[trade_symbols] if raw.terminal_returns is not None else None
                ),
                dividends=raw.dividends[trade_symbols] if raw.dividends is not None else None,
                stock_splits=raw.stock_splits[trade_symbols] if raw.stock_splits is not None else None,
                fx_to_base=raw.fx_to_base[trade_symbols] if raw.fx_to_base is not None else None,
                fx_age_days=raw.fx_age_days[trade_symbols] if raw.fx_age_days is not None else None,
                base_currency=raw.base_currency,
                exchange=raw.exchange,
            )
            strategy = StrategyConfig(
                max_weight=max_weight,
                rebalance_every=rebalance_every,
                regime_enabled=regime_enabled,
                factor_neutralization=factor_neutralization,
                factor_neutralization_strength=factor_neutralization_strength,
                risk_budget_penalty=risk_budget_penalty,
            )
            config = BacktestConfig(
                initial_cash=initial_cash,
                base_currency=base_currency,
                strategy=strategy,
            )
            comparison = historical_vs_paper_replay(trade_data, config, train_fraction=train_fraction)
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
                run_manifest = build_run_manifest(
                    config, input_snapshot.dataset_id, run_context=run_context
                )
                report_directory = f"artifacts/reports/{run_manifest.run_id}"
                exported_run, _ = export_research_report(
                    comparison.paper_replay,
                    config,
                    input_snapshot.dataset_id,
                    report_directory,
                    run_context=run_context,
                )
                report_verified = verify_research_report(report_directory)
                audit.append(
                    "REPORT_EXPORTED",
                    {
                        "run_id": exported_run.run_id,
                        "dataset_id": input_snapshot.dataset_id,
                        "path": report_directory,
                        "verified": report_verified,
                    },
                )
                report_export = (exported_run.run_id, report_directory, report_verified)
            benchmark_symbol = benchmark.strip().upper()
            benchmark_close_base = (
                raw.close[benchmark_symbol] * raw.fx_to_base[benchmark_symbol]
            ).ffill().dropna()
            persistent_nav = None
            persistent_orders = None
            persistent_fills = None
            persistent_positions = None
            persistent_snapshots = None
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
        if report_export is not None:
            report_run_id, report_path, report_verified = report_export
            st.success(
                f"M4 report 已匯出：{report_path}；run_id={report_run_id}；"
                f"integrity={'PASS' if report_verified else 'FAIL'}。"
            )
        session_report = comparison.paper_replay.session_validation
        if not action_report.is_valid:
            st.warning(
                "企業行動資料有可疑項目："
                f"負股利 {len(action_report.negative_dividend_events)}、"
                f"無效拆股 {len(action_report.invalid_split_events)}、"
                f"拆股後調整報酬異常 {len(action_report.suspicious_split_adjustments)}。"
            )
        if session_report is not None and (
            session_report.missing_sessions or session_report.off_calendar_sessions
        ):
            missing_preview = ", ".join(str(x.date()) for x in session_report.missing_sessions[:3])
            extra_preview = ", ".join(str(x.date()) for x in session_report.off_calendar_sessions[:3])
            st.warning(
                "市場資料與第三方交易日曆存在差異。"
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
            pt1, pt2, pt3, pt4 = st.tabs(
                ["Persistent Orders", "Persistent Fills", "Positions", "Daily Snapshots"]
            )
            with pt1:
                st.dataframe(persistent_orders, use_container_width=True, height=300)
            with pt2:
                st.dataframe(persistent_fills, use_container_width=True, height=300)
            with pt3:
                st.dataframe(persistent_positions, use_container_width=True, height=300)
            with pt4:
                st.dataframe(persistent_snapshots, use_container_width=True, height=300)

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
