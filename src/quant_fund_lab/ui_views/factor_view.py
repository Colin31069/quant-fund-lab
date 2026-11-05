"""UI view for cross-sectional factor research and learned factor alpha."""
from __future__ import annotations

import streamlit as st


def render_factor_laboratory(
    factor_research: object | None,
    enable_factor_alpha: bool,
    comparison: object,
    trade_symbols: list[str] | tuple[str, ...],
) -> None:
    """Render factor IC statistics, decay profiles, turnover, and learned alpha overlay."""
    if factor_research is not None:
        st.subheader("M5-1 Factor Research (橫斷面因子研究與 IC 衰減)")
        if factor_research.summary.empty:
            st.warning("目前資料不足以形成可用的 cross-sectional IC 統計。")
        else:
            st.caption(
                "IC / Rank IC 使用 factor timestamp 之後的 forward return；"
                "factor 本身只由當下與更早資料計算。正值代表因子排序方向與未來報酬同向。"
            )
            st.dataframe(factor_research.summary, use_container_width=True, height=360)
            f1, f2 = st.columns(2)
            with f1:
                st.markdown("**Rank IC Decay**")
                st.dataframe(factor_research.decay, use_container_width=True, height=300)
            with f2:
                st.markdown("**Factor Rank Turnover**")
                st.dataframe(
                    factor_research.turnover.rename("rank_turnover").to_frame(),
                    use_container_width=True,
                    height=300,
                )
            st.markdown("**Average Cross-sectional Factor Correlation**")
            st.dataframe(
                factor_research.factor_correlation,
                use_container_width=True,
                height=320,
            )

    if enable_factor_alpha:
        st.subheader("M5-2 Learned Factor Alpha (自適應因子權重疊加)")
        learned = comparison.paper_replay.factor_weights
        if learned.empty:
            st.info("尚未累積足夠已實現 IC 樣本；Factor overlay 暫時不改變原始 Alpha。")
        else:
            st.caption(
                "權重由 signal date 前已完整實現的 Rank IC 學習；5 日 horizon 使用非重疊樣本，"
                "並以 L1 正規化。正權重代表順向使用，負權重代表反向使用。"
            )
            st.dataframe(learned.tail(40), use_container_width=True, height=320)
        if len(trade_symbols) < 6:
            st.warning("目前股票數少於 6 檔，cross-sectional IC 估計會非常不穩定；較適合研究較大 universe。")
