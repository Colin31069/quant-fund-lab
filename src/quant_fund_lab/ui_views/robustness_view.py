"""UI view for robustness testing, block bootstrap, and walk-forward cross-validation."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from quant_fund_lab.diagnostics import diagnose_walk_forward
from quant_fund_lab.walkforward import (
    WalkForwardSpec,
    generate_candidate_grid,
    run_walk_forward,
)


def render_robustness_and_walkforward(
    robustness: object | None,
    run_walkforward: bool,
    trade_data: object,
    config: object,
    strategy: object,
    walkforward_objective: str,
    base_currency: str,
) -> None:
    """Render M5-4 Robustness Lab and Walk-forward OOS cross-validation with DSR diagnostics."""
    if robustness is not None:
        st.subheader("M5-4 Robustness Lab (參數穩健性與情境壓力檢定)")
        st.caption(
            "Robustness 結果只作診斷，不參與參數選擇：成本壓力固定為 1.0x / 1.5x / 2.0x；"
            "block bootstrap 保留短期報酬相依；regime attribution 只使用當時已知的最新 regime；"
            "raw 模式另測 dividend withholding 基準 ±10 個百分點。"
        )
        rb1, rb2, rb3, rb4 = st.tabs(
            [
                "Execution Cost Stress",
                "Block Bootstrap",
                "Regime Attribution",
                "Dividend Tax Sensitivity",
            ]
        )
        with rb1:
            st.dataframe(robustness.cost_stress, use_container_width=True, height=320)
        with rb2:
            st.dataframe(robustness.bootstrap_summary, use_container_width=True, height=320)
        with rb3:
            st.dataframe(robustness.regime_attribution, use_container_width=True, height=320)
        with rb4:
            if robustness.dividend_tax_sensitivity.empty:
                st.info("Dividend tax sensitivity 僅適用 raw-price corporate-action 模式。")
            else:
                st.dataframe(
                    robustness.dividend_tax_sensitivity,
                    use_container_width=True,
                    height=320,
                )

    if run_walkforward:
        st.subheader("Walk-forward Out-of-Sample (滾動前向樣本外檢定)")
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
                yaxis_title=f"NAV ({base_currency})",
                height=380,
            )
            st.plotly_chart(wf_fig, use_container_width=True)
