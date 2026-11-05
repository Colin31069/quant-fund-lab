"""Sidebar components for TWSE odd-lot research assumptions."""
from __future__ import annotations

import json
from dataclasses import dataclass

import streamlit as st

from quant_fund_lab.odd_lot_execution import default_instrument_rules


@dataclass(frozen=True)
class OddLotUIInputs:
    """UI inputs specific to TWSE odd-lot research assumptions."""

    odd_lot_risk: float
    odd_lot_fee: float
    odd_lot_commission: float
    odd_lot_slippage: float
    odd_lot_limit: float
    odd_lot_fill: int
    odd_lot_participation: float
    odd_lot_impact: float
    odd_lot_rounding: str
    instrument_rules_text: str
    holdout_untouched: bool


def render_odd_lot_assumptions(odd_lot_study: bool) -> OddLotUIInputs:
    """Render the TWSE odd-lot study assumptions form and return parameters."""
    odd_lot_risk = 2_000.0
    odd_lot_fee = 20.0
    odd_lot_commission = 14.25
    odd_lot_slippage = 5.0
    odd_lot_limit = 1.0
    odd_lot_fill = 50
    odd_lot_participation = 5.0
    odd_lot_impact = 0.10
    odd_lot_rounding = "fractional"
    instrument_rules_text = json.dumps(
        default_instrument_rules(), ensure_ascii=False, indent=2
    )
    holdout_untouched = False

    if odd_lot_study:
        st.markdown("**🇹🇼 台股零股研究假設**")
        odd_lot_risk = st.number_input(
            "單筆預估風險預算（TWD）", min_value=1.0, value=2_000.0, step=100.0
        )
        odd_lot_fee = st.number_input(
            "最低手續費情境（每筆 TWD）", min_value=0.0, value=20.0, step=1.0
        )
        odd_lot_commission = st.number_input(
            "手續費率（bps）", min_value=0.0, value=14.25, step=0.25
        )
        odd_lot_slippage = st.number_input(
            "滑價情境（bps）", min_value=0.0, value=5.0, step=1.0
        )
        odd_lot_limit = st.number_input(
            "限價距權息調整參考價（%）",
            min_value=0.0,
            max_value=99.0,
            value=1.0,
            step=0.5,
        )
        odd_lot_fill = st.slider("單筆委託模擬成交比例（%）", 1, 100, 50)
        odd_lot_participation = st.number_input(
            "歷史普通成交量參與率上限（%）",
            min_value=0.01,
            max_value=100.0,
            value=5.0,
            step=1.0,
        )
        odd_lot_impact = st.number_input(
            "市場衝擊係數", min_value=0.0, value=0.10, step=0.01
        )
        odd_lot_rounding = st.selectbox(
            "手續費與證交稅進位假設",
            ["fractional", "floor", "nearest"],
            format_func=lambda x: {
                "fractional": "保留小數",
                "floor": "捨去至元",
                "nearest": "四捨五入至元",
            }[x],
        )
        instrument_rules_text = st.text_area(
            "交易標的規則（JSON）",
            value=json.dumps(
                default_instrument_rules(), ensure_ascii=False, indent=2
            ),
            help=(
                "每個交易標的須明確指定 kind（stock/etf）、sell_tax_bps、price_limit_pct；"
                "null 表示無漲跌幅限制。這是全研究期間的情境假設，不會自動辨識歷史例外。"
            ),
        )
        holdout_untouched = st.checkbox(
            "確認 2025 年後資料尚未用於此策略調參", value=False
        )
        st.caption(
            "整股開盤及歷史成交量僅為零股代理，成交比例並非真實成交機率；"
            "收盤觸發止損，次交易日嘗試退出。T+2 以資料交易日代理，賣款在當日開盤後入帳。"
        )
        st.caption(
            "進階 Factor / CVaR / Walk-forward 設定不套用於此研究；"
            "帳本存檔只供稽核，無法續跑。"
        )

    return OddLotUIInputs(
        odd_lot_risk=odd_lot_risk,
        odd_lot_fee=odd_lot_fee,
        odd_lot_commission=odd_lot_commission,
        odd_lot_slippage=odd_lot_slippage,
        odd_lot_limit=odd_lot_limit,
        odd_lot_fill=odd_lot_fill,
        odd_lot_participation=odd_lot_participation,
        odd_lot_impact=odd_lot_impact,
        odd_lot_rounding=odd_lot_rounding,
        instrument_rules_text=instrument_rules_text,
        holdout_untouched=holdout_untouched,
    )
