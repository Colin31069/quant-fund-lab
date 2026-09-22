from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from quant_fund_lab.analytics import buy_and_hold_equity, metric_frame
from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import MarketData, download_yahoo, synthetic_market_data
from quant_fund_lab.data_quality import validate_corporate_actions
from quant_fund_lab.diagnostics import diagnose_walk_forward
from quant_fund_lab.fx import attach_fx_rates, attach_yahoo_fx, validate_fx
from quant_fund_lab.paper import historical_vs_paper_replay
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
    run = st.button("執行模型", type="primary", use_container_width=True)


@st.cache_data(show_spinner=False)
def load_data(mode: str, symbols: tuple[str, ...], start: str, end: str) -> MarketData:
    if mode == "離線合成資料":
        return synthetic_market_data(symbols=symbols, periods=800)
    return download_yahoo(symbols=symbols, start=start, end=end)


if run:
    trade_symbols = [s.strip().upper() for s in symbols_text.split(",") if s.strip()]
    all_symbols = list(dict.fromkeys(trade_symbols + [benchmark.strip().upper()]))
    if len(trade_symbols) < 2:
        st.error("至少提供兩個交易標的，橫斷面模型才有意義。")
        st.stop()

    try:
        with st.spinner("載入資料並執行 walk-forward paper replay..."):
            raw = load_data(data_mode, tuple(all_symbols), str(start_date), str(end_date + timedelta(days=1)))
            if data_mode == "Yahoo 公開市場資料":
                raw = attach_yahoo_fx(raw, base_currency=base_currency)
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
            strategy = StrategyConfig(max_weight=max_weight, rebalance_every=rebalance_every)
            config = BacktestConfig(
                initial_cash=initial_cash,
                base_currency=base_currency,
                strategy=strategy,
            )
            comparison = historical_vs_paper_replay(trade_data, config, train_fraction=train_fraction)
            action_report = validate_corporate_actions(trade_data)
            fx_report = validate_fx(trade_data, config.max_fx_staleness_days)

        st.success(
            f"切分日：{comparison.split_date.date()}；其後區段以重置虛擬資金做 paper replay。"
            f" NAV 基準幣別：{comparison.paper_replay.base_currency}。"
        )
        st.caption(
            f"FX 最大沿用天數：{fx_report.max_age_days:.0f} 日；"
            "換匯只允許使用當日或更早的匯率，不使用未來資料。"
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
            benchmark_symbol = benchmark.strip().upper()
            benchmark_close = (
                raw.close[benchmark_symbol] * raw.fx_to_base[benchmark_symbol]
            ).reindex(paper_equity.index).ffill().dropna()
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
