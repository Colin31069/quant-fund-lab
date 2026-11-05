"""Sidebar controls for factor research, alpha overlays, and risk management."""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st


@dataclass(frozen=True)
class RiskAndFactorInputs:
    """UI inputs for factor modeling and risk management parameters."""

    run_factor_research: bool
    enable_factor_alpha: bool
    factor_alpha_weight: float
    regime_enabled: bool
    factor_neutralization: bool
    factor_neutralization_strength: float
    risk_budget_penalty: float
    enable_vol_target: bool
    target_annual_volatility: float
    enable_cvar_control: bool
    max_daily_cvar: float
    enable_drawdown_control: bool
    drawdown_soft_limit: float
    drawdown_hard_limit: float
    drawdown_min_exposure: float
    run_robustness: bool


def render_risk_and_factors(odd_lot_study: bool) -> RiskAndFactorInputs:
    """Render factor research and dynamic risk control sections in sidebar."""
    st.markdown("**📈 因子與 Alpha 模型**")
    run_factor_research = st.checkbox(
        "執行因子 IC / Decay 研究", value=False, disabled=odd_lot_study
    )
    enable_factor_alpha = st.checkbox(
        "啟用 trailing-IC Factor Alpha overlay",
        value=False,
        disabled=odd_lot_study,
    )
    factor_alpha_weight = st.slider(
        "Factor Alpha overlay 權重", 0.0, 0.60, 0.30, 0.05
    )

    st.markdown("**🛡️ 動態風控與政權**")
    regime_enabled = st.checkbox("Regime detection", value=True)
    factor_neutralization = st.checkbox("Factor neutralization", value=True)
    factor_neutralization_strength = st.slider(
        "Factor neutralization strength", 0.0, 1.0, 0.50, 0.10
    )
    risk_budget_penalty = st.slider(
        "Risk-budget penalty", 0.0, 0.010, 0.001, 0.001, format="%.3f"
    )
    enable_vol_target = st.checkbox(
        "Volatility targeting", value=False, disabled=odd_lot_study
    )
    target_annual_volatility = st.slider("目標年化波動", 0.05, 0.30, 0.12, 0.01)
    enable_cvar_control = st.checkbox(
        "CVaR / Expected Shortfall cap", value=False, disabled=odd_lot_study
    )
    max_daily_cvar = st.slider(
        "最大日 CVaR", 0.005, 0.050, 0.025, 0.005, format="%.3f"
    )
    enable_drawdown_control = st.checkbox(
        "Drawdown de-risking", value=False, disabled=odd_lot_study
    )
    drawdown_soft_limit = st.slider("Drawdown soft limit", 0.05, 0.20, 0.10, 0.01)
    drawdown_hard_min = min(drawdown_soft_limit + 0.05, 0.40)
    drawdown_hard_limit = st.slider(
        "Drawdown hard limit",
        drawdown_hard_min,
        0.50,
        max(0.20, drawdown_hard_min),
        0.01,
    )
    drawdown_min_exposure = st.slider("Hard-limit 最低風險曝險", 0.0, 0.75, 0.25, 0.05)
    run_robustness = st.checkbox(
        "執行 M5-4 Robustness Lab", value=False, disabled=odd_lot_study
    )

    return RiskAndFactorInputs(
        run_factor_research=run_factor_research,
        enable_factor_alpha=enable_factor_alpha,
        factor_alpha_weight=factor_alpha_weight,
        regime_enabled=regime_enabled,
        factor_neutralization=factor_neutralization,
        factor_neutralization_strength=factor_neutralization_strength,
        risk_budget_penalty=risk_budget_penalty,
        enable_vol_target=enable_vol_target,
        target_annual_volatility=target_annual_volatility,
        enable_cvar_control=enable_cvar_control,
        max_daily_cvar=max_daily_cvar,
        enable_drawdown_control=enable_drawdown_control,
        drawdown_soft_limit=drawdown_soft_limit,
        drawdown_hard_limit=drawdown_hard_limit,
        drawdown_min_exposure=drawdown_min_exposure,
        run_robustness=run_robustness,
    )
