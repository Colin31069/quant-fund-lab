"""Interactive Plotly charts for equity curves and drawdowns."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots


def render_equity_charts(
    comparison: object,
    benchmark_equity: pd.Series | None = None,
) -> None:
    """Render interactive standardized equity curves and underwater drawdown analysis."""
    bt = comparison.backtest.equity_curve["equity"]
    pp = comparison.paper_replay.equity_curve["equity"]

    # Main Growth of 1 Figure (Preserving exact layout title expected by downstream tools)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=bt.index,
            y=bt / bt.iloc[0],
            name="Historical backtest",
            line={"color": "#1f77b4", "width": 2},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=pp.index,
            y=pp / pp.iloc[0],
            name="Paper replay",
            line={"color": "#2ca02c", "width": 2.5},
        )
    )
    if benchmark_equity is not None and not benchmark_equity.empty:
        bmk_aligned = benchmark_equity.reindex(pp.index).ffill().dropna()
        if not bmk_aligned.empty:
            fig.add_trace(
                go.Scatter(
                    x=bmk_aligned.index,
                    y=bmk_aligned / bmk_aligned.iloc[0],
                    name="Benchmark",
                    line={"color": "#7f7f7f", "width": 1.5, "dash": "dot"},
                )
            )

    fig.update_layout(
        title="標準化淨值曲線",
        yaxis_title="Growth of 1",
        xaxis_title="交易日",
        height=450,
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )
    st.plotly_chart(fig, use_container_width=True)

    # Optional Underwater Drawdown Expander for deep dive
    with st.expander("🌊 水下回撤深度圖 (Underwater Drawdown Profile)", expanded=False):
        dd_fig = go.Figure()
        pp_dd = (pp / pp.cummax()) - 1.0
        dd_fig.add_trace(
            go.Scatter(
                x=pp_dd.index,
                y=pp_dd,
                name="Paper Replay Drawdown",
                fill="tozeroy",
                line={"color": "#d62728", "width": 1.5},
            )
        )
        if benchmark_equity is not None and not benchmark_equity.empty:
            bmk_aligned = benchmark_equity.reindex(pp.index).ffill().dropna()
            if not bmk_aligned.empty:
                bmk_dd = (bmk_aligned / bmk_aligned.cummax()) - 1.0
                dd_fig.add_trace(
                    go.Scatter(
                        x=bmk_dd.index,
                        y=bmk_dd,
                        name="Benchmark Drawdown",
                        line={"color": "#7f7f7f", "width": 1, "dash": "dot"},
                    )
                )
        dd_fig.update_layout(
            title="歷史回撤水下走勢 (Underwater Drawdown)",
            yaxis_title="Drawdown (%)",
            yaxis_tickformat=".1%",
            xaxis_title="交易日",
            height=300,
            hovermode="x unified",
        )
        st.plotly_chart(dd_fig, use_container_width=True)


def render_odd_lot_equity_chart(
    equity_curve: pd.DataFrame, title: str = "策略淨值與回撤走勢"
) -> None:
    """Render interactive Plotly equity curve with underwater drawdown subplot."""
    if equity_curve.empty or "equity" not in equity_curve.columns:
        st.info("無足夠淨值數據可供繪圖。")
        return

    equity = equity_curve["equity"].dropna().astype(float)
    if len(equity) < 2:
        st.info("淨值數據點不足兩筆，無法繪製互動圖表。")
        return

    hwm = equity.cummax()
    drawdown = (equity / hwm) - 1.0

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.65, 0.35],
        subplot_titles=("資產淨值曲線 (Portfolio Equity)", "歷史水下回撤 (Underwater Drawdown)"),
    )

    # 1. Equity trace
    fig.add_trace(
        go.Scatter(
            x=equity.index,
            y=equity,
            mode="lines",
            name="資產淨值 (Equity)",
            line={"color": "#1f77b4", "width": 2},
            hovertemplate="%{x}<br>淨值: %{y:,.0f} 元<extra></extra>",
        ),
        row=1,
        col=1,
    )

    # 2. High-Water Mark trace
    fig.add_trace(
        go.Scatter(
            x=hwm.index,
            y=hwm,
            mode="lines",
            name="歷史峰值 (High-Water Mark)",
            line={"color": "#aec7e8", "width": 1.2, "dash": "dash"},
            hovertemplate="%{x}<br>歷史峰值: %{y:,.0f} 元<extra></extra>",
        ),
        row=1,
        col=1,
    )

    # 3. Optional settled cash trace (toggleable in legend)
    if "settled_cash" in equity_curve.columns:
        settled = equity_curve["settled_cash"].reindex(equity.index).ffill().dropna().astype(float)
        fig.add_trace(
            go.Scatter(
                x=settled.index,
                y=settled,
                mode="lines",
                name="已交割現金 (Settled Cash)",
                line={"color": "#2ca02c", "width": 1, "dash": "dot"},
                visible="legendonly",
                hovertemplate="%{x}<br>現金: %{y:,.0f} 元<extra></extra>",
            ),
            row=1,
            col=1,
        )

    # 4. Underwater Drawdown trace
    fig.add_trace(
        go.Scatter(
            x=drawdown.index,
            y=drawdown,
            mode="lines",
            name="水下回撤 (Drawdown)",
            fill="tozeroy",
            line={"color": "#d62728", "width": 1.5},
            hovertemplate="%{x}<br>回撤: %{y:.2%}<extra></extra>",
        ),
        row=2,
        col=1,
    )

    fig.update_layout(
        title=title,
        height=520,
        hovermode="x unified",
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1.0,
        },
        margin={"l": 40, "r": 30, "t": 60, "b": 30},
    )
    fig.update_yaxes(title_text="金額 (TWD)", tickformat=",", row=1, col=1)
    fig.update_yaxes(title_text="回撤幅度", tickformat=".1%", row=2, col=1)
    fig.update_xaxes(title_text="交易日", row=2, col=1)

    st.plotly_chart(fig, use_container_width=True)
