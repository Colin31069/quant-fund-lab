"""UI view for persistent SQLite paper trading ledger and accounting audit."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from quant_fund_lab.tax_analytics import summarize_dividend_tax


def render_persistent_ledger(
    persistent_nav: pd.DataFrame | None,
    persistent_orders: pd.DataFrame | None,
    persistent_fills: pd.DataFrame | None,
    persistent_positions: pd.DataFrame | None,
    persistent_snapshots: pd.DataFrame | None,
    persistent_actions: pd.DataFrame | None,
    persistent_receivables: pd.DataFrame | None,
    persistent_interest_credits: pd.DataFrame | None,
    persistent_session_commits: pd.DataFrame | None,
    persistent_replay_execution_config: dict | None,
    persistent_ledger_audit: object | None,
    paper_ledger_reset: bool,
    base_currency: str,
    config: object,
) -> None:
    """Render SQLite persistent paper ledger state, metrics, charts, and 10 audit tabs."""
    if persistent_nav is None or persistent_nav.empty:
        return

    st.subheader("M3 Persistent Paper Ledger (SQLite 持久化帳本與雙重記帳稽核)")
    st.success(
        "M11-6 虛擬帳本："
        + ("已建立新帳本" if paper_ledger_reset else "已核對並安全續跑既有帳本")
        + f"；目前共 {len(persistent_nav)} 個已完成交易日。"
    )
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
    open_receivable_count = int(
        persistent_receivables["status"].eq("OPEN").sum()
        if persistent_receivables is not None and not persistent_receivables.empty
        else 0
    )
    st.caption(
        "Cash-in-lieu receivables：open "
        f"{open_receivable_count}；current NAV mark "
        f"{float(latest_nav.get('receivable_value', 0.0)):,.2f} {base_currency}。"
    )
    st.caption(
        "M11-2 Cash carry：today "
        f"{float(latest_nav['cash_interest']):,.2f}；cumulative "
        f"{float(latest_nav['cumulative_cash_interest']):,.2f} "
        f"{base_currency}；locked annual yield {config.cash_annual_yield:.2%}。"
    )
    st.caption(
        "M11-3 Atomic sessions：committed "
        f"{len(persistent_session_commits)} / {len(persistent_nav)} NAV sessions；"
        "每日利息、成交、企業行動、NAV 與收盤目標訂單同筆 SQLite 交易提交。"
    )
    st.caption(
        "M11-4 Replay data lock：每個完成日保存價格、成交量、FX、"
        "企業行動、執行參考價及 benchmark 的 SHA-256 指紋；"
        "續跑前逐日核對，細節請見 Session Commits 分頁。"
    )
    st.caption(
        "M11-5 Execution / Snapshot audit：固定交易成本、撮合及 FX 假設；"
        "續跑前校驗已提交 snapshot 的 SQLite 連結、manifest、檔案 hash "
        "及每日重播輸入指紋。"
    )
    if persistent_ledger_audit.is_valid:
        st.success(
            "M11-8 Independent ledger audit：PASS；"
            f"已核對 {persistent_ledger_audit.nav_sessions} 個 NAV、"
            f"{persistent_ledger_audit.fills} 筆成交及 "
            f"{persistent_ledger_audit.cash_credits} 筆現金入息，"
            "並重建逐日現金流與損益。"
        )
    else:
        st.error(
            "M11-8 Independent ledger audit：FAIL；"
            + persistent_ledger_audit.issues[0]
        )
    persistent_tax = summarize_dividend_tax(persistent_actions)
    st.caption(
        "Dividend cashflow：gross "
        f"{float(persistent_tax['gross_dividend_cash']):,.2f}；withholding "
        f"{float(persistent_tax['withholding_tax']):,.2f}；net "
        f"{float(persistent_tax['net_dividend_cash']):,.2f}；effective rate "
        f"{float(persistent_tax['effective_withholding_rate']):.1%}。"
    )
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
    pt1, pt2, pt3, pt4, pt5, pt6, pt7, pt8, pt9, pt10 = st.tabs(
        [
            "Persistent Orders",
            "Persistent Fills",
            "Positions",
            "Corporate Actions",
            "Cash-in-Lieu Receivables",
            "Cash Interest Credits",
            "Session Commits",
            "Daily Snapshots",
            "Execution Assumptions",
            "Ledger Accounting Audit",
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
        st.dataframe(persistent_receivables, use_container_width=True, height=300)
    with pt6:
        st.dataframe(persistent_interest_credits, use_container_width=True, height=300)
    with pt7:
        st.dataframe(persistent_session_commits, use_container_width=True, height=300)
    with pt8:
        st.dataframe(persistent_snapshots, use_container_width=True, height=300)
    with pt9:
        st.json(persistent_replay_execution_config)
    with pt10:
        st.json(
            {
                "passed": persistent_ledger_audit.is_valid,
                "nav_sessions": persistent_ledger_audit.nav_sessions,
                "fills": persistent_ledger_audit.fills,
                "position_marks": persistent_ledger_audit.position_marks,
                "cash_credits": persistent_ledger_audit.cash_credits,
                "issues": list(persistent_ledger_audit.issues),
            }
        )
