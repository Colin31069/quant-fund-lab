"""UI view for Taiwan odd-lot strategy study."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from quant_fund_lab.odd_lot_study import (
    OddLotStudyResult,
    load_frozen_odd_lot_study,
    verify_odd_lot_study_report,
)
from quant_fund_lab.twse_quality.ui import render_readiness
from quant_fund_lab.ui_views.charts import render_odd_lot_equity_chart


def _format_pct(val: object, decimals: int = 1) -> str:
    """Format floating number into percentage string safely."""
    if val is None or pd.isna(val):
        return "N/A"
    try:
        return f"{float(val):.{decimals}%}"
    except (ValueError, TypeError):
        return "N/A"


def _format_float(val: object, decimals: int = 2) -> str:
    """Format floating number safely."""
    if val is None or pd.isna(val):
        return "N/A"
    try:
        return f"{float(val):.{decimals}f}"
    except (ValueError, TypeError):
        return "N/A"


def _select_representative_row(comparison: pd.DataFrame) -> pd.Series | None:
    """Select the primary representative row (validation/ensemble, or ensemble, or first non-proxy)."""
    if comparison.empty:
        return None
    if "strategy" in comparison.columns:
        valid_strategies = comparison[
            ~comparison["strategy"].astype(str).str.contains("proxy|benchmark", case=False)
        ]
        if not valid_strategies.empty:
            if "period" in valid_strategies.columns:
                val = valid_strategies[
                    (valid_strategies["period"] == "validation")
                    & (valid_strategies["strategy"] == "ensemble")
                ]
                if not val.empty:
                    return val.iloc[0]
                ens = valid_strategies[valid_strategies["strategy"] == "ensemble"]
                if not ens.empty:
                    return ens.iloc[0]
            return valid_strategies.iloc[0]
    return comparison.iloc[0]


def _render_executive_kpis(comparison: pd.DataFrame) -> None:
    """Render executive KPI cards summarizing overall performance."""
    st.markdown("### 📊 核心績效總覽 (Executive Performance Summary)")
    target_row = _select_representative_row(comparison)
    if target_row is None:
        return

    period = str(target_row.get("period", ""))
    strategy = str(target_row.get("strategy", ""))
    label_parts = [p for p in (period, strategy) if p]
    if label_parts:
        st.caption(f"聚焦策略：{' / '.join(label_parts)}")

    c1, c2, c3, c4, c5, c6 = st.columns(6)

    # 1. Cumulative Return
    total_ret = target_row.get("total_return")
    c1.metric(
        "累積總報酬",
        _format_pct(total_ret),
        help="全期資產累積總報酬率 (Total Return)",
    )

    # 2. Annualized Return (CAGR)
    ann_ret = target_row.get("annual_return")
    c2.metric(
        "年化報酬率",
        _format_pct(ann_ret),
        help="幾何年化複合成長率 (CAGR)",
    )

    # 3. Sharpe Ratio
    sharpe = target_row.get("sharpe")
    c3.metric(
        "夏普比率",
        _format_float(sharpe, 2),
        help="年化夏普比率 (Sharpe Ratio，無風險利率假設 0%)",
    )

    # 4. Max Drawdown
    mdd = target_row.get("max_drawdown")
    c4.metric(
        "最大回撤 (MaxDD)",
        _format_pct(mdd),
        help="歷史峰值至谷底之最大跌幅 (Max Drawdown)",
    )

    # 5. Win Rate & Payoff
    win_rate = target_row.get("win_rate")
    payoff = target_row.get("payoff_ratio")
    payoff_str = f"盈虧比 {_format_float(payoff, 2)}" if pd.notna(payoff) and payoff is not None else None
    c5.metric(
        "交易勝率",
        _format_pct(win_rate),
        delta=payoff_str,
        delta_color="off",
        help="平倉勝率 (Wins / Closed Episodes) 及平均獲利/平均虧損盈虧比",
    )

    # 6. Total Episodes
    closed = target_row.get("closed_count")
    opened = target_row.get("open_count")
    open_str = f"未平倉 {int(opened)}" if pd.notna(opened) and opened and int(opened) > 0 else None
    c6.metric(
        "交易次數",
        f"{int(closed)} 筆" if pd.notna(closed) and closed is not None else "N/A",
        delta=open_str,
        delta_color="off",
        help="已平倉交易筆數 (若 <30 筆代表統計樣本偏少)",
    )


def render_odd_lot_study(
    study: OddLotStudyResult, frozen: Path, report: Path, provider: str
) -> None:
    """Render Taiwan odd-lot study results, metrics, and episode details."""
    st.subheader("台股零股策略研究")
    st.warning(
        "價格與成交量是普通交易資料的代理，不能保證零股成交或止損；"
        "現存股票示例池有存活者偏差。"
    )
    if provider == "synthetic":
        st.warning("目前為合成測試資料，不代表真實市場或策略績效。")
    if not study.holdout_untouched:
        st.warning("2025 年後資料是否已用於調參未確認；歷史評估應視為探索性結果。")
    st.caption(f"研究 ID：{study.study_id}；資料 ID：{study.dataset_id}。")
    if study.readiness_fingerprint:
        metadata = load_frozen_odd_lot_study(frozen)[1]
        render_readiness(st, metadata["readiness"], study.readiness_fingerprint)
    report_valid = verify_odd_lot_study_report(report)
    st.caption(
        f"凍結資料：{frozen}；報告：{report}；報告校驗：{'PASS' if report_valid else 'FAIL'}。"
    )
    if provider == "provider_reviewed":
        st.caption("依凍結政策選用 TWSE／FinMind 原始價量；各筆來源及衝突見逐日來源清單。")
        if report_valid:
            st.download_button(
                "下載逐日來源清單",
                (report / "price_selection.csv").read_bytes(),
                file_name="price_selection.csv",
                mime="text/csv",
            )
    if not study.comparison.empty:
        _render_executive_kpis(study.comparison)
    st.dataframe(study.comparison, use_container_width=True)
    st.caption(
        "完整交易少於 30 筆標示樣本不足；30 筆以上也不代表策略已獲證實。市場基準是未扣交易成本的總報酬代理。"
    )
    st.caption("供應商價格是否為真實未調整價格、股息實際入帳時間與零股歷史成交價尚未獨立驗證。")
    if study.unavailable:
        st.info(
            "部分期間資料不足："
            + "; ".join(f"{key}: {value}" for key, value in study.unavailable.items())
        )
    st.subheader("手續費、滑價與成交比例敏感度（2024 驗證期）")
    st.dataframe(study.sensitivity, use_container_width=True)
    keys = list(study.results)
    if keys:
        selected = st.selectbox(
            "研究明細", keys, format_func=lambda item: f"{item[0]} / {item[1]}"
        )
        detail = study.results[selected]
        render_odd_lot_equity_chart(
            detail.equity_curve,
            title=f"淨值與回撤走勢（{selected[0]} / {selected[1]}）",
        )
        a, b, c, d, e = st.tabs(
            ["完整與未平倉交易", "進出場訊號", "成交紀錄", "限價委託", "交割明細"]
        )
        with a:
            st.dataframe(detail.episodes, use_container_width=True)
        with b:
            st.dataframe(detail.signals, use_container_width=True)
        with c:
            st.dataframe(detail.fills, use_container_width=True)
        with d:
            st.dataframe(detail.orders, use_container_width=True)
        with e:
            st.dataframe(detail.settlements, use_container_width=True)
            st.dataframe(
                detail.equity_curve[
                    [
                        "cash",
                        "settled_cash",
                        "buy_payables",
                        "sale_receivables",
                        "sale_payables",
                    ]
                ],
                use_container_width=True,
            )
