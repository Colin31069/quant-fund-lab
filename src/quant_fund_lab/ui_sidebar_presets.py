"""Sidebar presets documentation and quick configuration templates."""
from __future__ import annotations

import streamlit as st


def render_sidebar_presets() -> None:
    """Render friendly guidance for quick preset configurations."""
    with st.expander("⚡ 快速範本預設 (Quick Presets)", expanded=False):
        st.markdown(
            "可依據研究目標參考以下標準設定組合：\n\n"
            "- **⚡ 離線合成測試 (Synthetic Smoke Test)**\n"
            "  - 資料來源：`離線合成資料`\n"
            "  - 標的：`AAPL,MSFT,NVDA,GOOGL` / 基準：`SPY`\n"
            "  - 特點：純本機數值運算，無需外部網路或資料包，適合快速驗證邏輯。\n\n"
            "- **🇹🇼 台股十萬零股動能 (TWSE Odd-Lot)**\n"
            "  - 勾選：`十萬元台股零股策略研究`\n"
            "  - 資料來源：`TWSE 官方歷史資料` 或 `TWSE＋FinMind 本機資料`\n"
            "  - 初始資金：`100,000 TWD` / 成交基準：`raw`\n"
            "  - 特點：模擬台股升降單位、手續費低消、盤中零股流動性與企業行動。\n\n"
            "- **🇺🇸 美股大型科技動能 (US Tech Large-Cap)**\n"
            "  - 資料來源：`Yahoo 公開市場資料` 或 `離線合成資料`\n"
            "  - 標的：`AAPL,MSFT,NVDA,GOOGL` / 基準：`SPY` / 幣別：`USD`\n"
            "  - 特點：支援跨期 Walk-forward OOS、動態風控與 Factor Alpha 疊加。"
        )
