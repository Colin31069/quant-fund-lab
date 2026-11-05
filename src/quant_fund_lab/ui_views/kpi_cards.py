"""Executive KPI cards and benchmark comparison for quantitative backtest results."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from quant_fund_lab.analytics import buy_and_hold_equity, metric_frame


def render_kpi_dashboard(
    comparison: object,
    benchmark_close_base: pd.Series,
    initial_cash: float,
) -> tuple[pd.DataFrame, pd.Series]:
    """Render high-level executive KPI cards followed by detailed comparison tables."""
    paper_equity = comparison.paper_replay.equity_curve["equity"]
    benchmark_close = benchmark_close_base.reindex(paper_equity.index).ffill().dropna()
    benchmark_equity = buy_and_hold_equity(benchmark_close, initial_cash)
    comparison_frame = metric_frame(
        {"paper_replay": paper_equity, "benchmark": benchmark_equity}
    )

    # Executive Summary Hero Cards
    st.markdown("### 📊 核心績效總覽 (Executive Performance Summary)")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    if "paper_replay" in comparison_frame.index and "benchmark" in comparison_frame.index:
        strat_tot = float(comparison_frame.loc["paper_replay", "total_return"])
        bmk_tot = float(comparison_frame.loc["benchmark", "total_return"])
        strat_ann = float(comparison_frame.loc["paper_replay", "annual_return"])
        strat_sharpe = float(comparison_frame.loc["paper_replay", "sharpe"])
        strat_mdd = float(comparison_frame.loc["paper_replay", "max_drawdown"])
        strat_calmar = float(comparison_frame.loc["paper_replay", "calmar"])
        strat_vol = float(comparison_frame.loc["paper_replay", "annual_volatility"])

        delta_tot = f"{(strat_tot - bmk_tot):+.1%}" if not pd.isna(bmk_tot) else None
        c1.metric(
            "累積總報酬",
            f"{strat_tot:.1%}",
            delta=delta_tot,
            help="Paper Replay 模擬重播之全期累積報酬率，Delta 為相對基準超額報酬",
        )
        c2.metric("年化報酬率 (CAGR)", f"{strat_ann:.1%}", help="幾何年化複合成長率")
        c3.metric("夏普比率 (Sharpe)", f"{strat_sharpe:.2f}", help="無風險利率以 0% 假設計算之年化夏普比率")
        c4.metric("最大回撤 (MaxDD)", f"{strat_mdd:.1%}", help="歷史峰值至谷底之最大資產跌幅")
        c5.metric("卡瑪比率 (Calmar)", f"{strat_calmar:.2f}", help="年化報酬率 / 最大回撤")
        c6.metric("年化波動率", f"{strat_vol:.1%}", help="日報酬率經年化調整之標準差")

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
        st.dataframe(comparison_frame, use_container_width=True)

    return comparison_frame, benchmark_equity
