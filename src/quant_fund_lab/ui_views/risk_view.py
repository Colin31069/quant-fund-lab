"""UI view for portfolio risk controls, regime shifts, and risk budgeting."""
from __future__ import annotations

import streamlit as st


def render_risk_and_regime(
    comparison: object,
    enable_vol_target: bool,
    enable_cvar_control: bool,
    enable_drawdown_control: bool,
    factor_neutralization: bool,
    factor_neutralization_strength: float,
    risk_budget_penalty: float,
) -> None:
    """Render dynamic risk controls (vol targeting, CVaR, drawdown limits) and regime detection."""
    if enable_vol_target or enable_cvar_control or enable_drawdown_control:
        st.subheader("M5-3 Portfolio Risk Controls (多維動態風險控制)")
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

    st.subheader("M2-3 Regime / Risk Budget (市場政權偵測與風險預算)")
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
