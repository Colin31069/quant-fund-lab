"""UI view for transaction friction, dividend taxes, cash carry, and settlement."""
from __future__ import annotations

import streamlit as st

from quant_fund_lab.cash_in_lieu_analytics import cash_in_lieu_by_source, summarize_cash_in_lieu
from quant_fund_lab.tax_analytics import dividend_tax_by_currency, summarize_dividend_tax


def render_tax_and_settlement(comparison: object, config: object) -> None:
    """Render dividend withholding tax, cash interest, and cash-in-lieu settlement."""
    tax_summary = summarize_dividend_tax(comparison.paper_replay.corporate_actions)
    st.caption(
        "M11-1 現金收益（paper replay）："
        f"{float(comparison.paper_replay.equity_curve['cash_interest'].sum()):,.2f} "
        f"{comparison.paper_replay.base_currency}；"
        f"設定年收益率 {float(config.cash_annual_yield):.2%}。"
    )
    st.subheader("M9-3 Dividend Tax Drag (股息預扣稅衝擊)")
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Gross dividend", f"{float(tax_summary['gross_dividend_cash']):,.2f}")
    t2.metric("Withholding tax", f"{float(tax_summary['withholding_tax']):,.2f}")
    t3.metric("Net dividend", f"{float(tax_summary['net_dividend_cash']):,.2f}")
    t4.metric(
        "Effective withholding",
        f"{float(tax_summary['effective_withholding_rate']):.1%}",
    )
    tax_currency = dividend_tax_by_currency(comparison.paper_replay.corporate_actions)
    if not tax_currency.empty:
        st.dataframe(tax_currency, use_container_width=True)

    cil_summary = summarize_cash_in_lieu(comparison.paper_replay.corporate_actions)
    st.subheader("M10-6 Cash-in-Lieu Settlement (碎股折現款交割)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fractional splits", str(int(cil_summary["fractional_split_event_count"])))
    c2.metric("Delayed", str(int(cil_summary["delayed_receivable_count"])))
    c3.metric("Fallback", str(int(cil_summary["raw_open_fallback_count"])))
    c4.metric("Settled cash", f"{float(cil_summary['cash_in_lieu_cash']):,.2f}")
    st.caption(
        "Settlement lag：avg "
        f"{float(cil_summary['average_settlement_lag_days']):.1f} days；max "
        f"{float(cil_summary['max_settlement_lag_days']):.1f} days；"
        f"unresolved {int(cil_summary['unresolved_receivable_count'])}。"
    )
    cil_sources = cash_in_lieu_by_source(comparison.paper_replay.corporate_actions)
    if not cil_sources.empty:
        st.dataframe(cil_sources, use_container_width=True)


def render_trading_details(comparison: object) -> None:
    """Render orders, fills, cost attribution, target weights, and alpha signals."""
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
