"""Sidebar TWSE official file and batch import tools."""
from __future__ import annotations

import streamlit as st

from quant_fund_lab.twse_odd_lot import import_twse_file
from quant_fund_lab.twse_preparation import batch_import_twse, read_batch_manifest


def render_twse_import_tools(twse_directory: str) -> None:
    """Render TWSE official file single and batch import expandable forms."""
    with st.expander("匯入已下載的證交所檔案"):
        import_path = st.text_input("官方 JSON／CSV 檔案路徑")
        import_kind = st.selectbox(
            "檔案類型",
            [
                "price",
                "ex_right_index",
                "etf_split_index",
                "par_change_index",
                "reduction_index",
                "holiday_index",
            ],
        )
        import_url = st.text_input("證交所來源網址", "https://www.twse.com.tw/")
        import_symbol = st.text_input("價格股票代碼", "2330.TW")
        import_month = st.text_input("價格月份（YYYY-MM）", "2025-06")
        import_year = st.number_input(
            "企業行動索引年度", min_value=2010, max_value=2100, value=2025
        )
        if st.button("匯入官方檔案"):
            try:
                imported = import_twse_file(
                    twse_directory,
                    import_path,
                    kind=import_kind,
                    source_url=import_url,
                    symbol=import_symbol,
                    month=import_month,
                    year=int(import_year),
                )
                st.success(f"已匯入：{imported}")
            except (OSError, ValueError, KeyError) as exc:
                st.error(f"匯入失敗：{exc}")
    with st.expander("批次匯入官方檔案"):
        st.caption(
            "準備 CSV 清單：file,kind,source_url,symbol,month,year；相對路徑以清單所在目錄為準。"
        )
        batch_path = st.text_input("批次清單 CSV 路徑")
        preview_batch = st.button("預覽批次匯入")
        import_batch = st.button("執行批次匯入")
        if preview_batch or import_batch:
            try:
                rows = read_batch_manifest(batch_path)
                result = batch_import_twse(
                    twse_directory, rows, dry_run=not import_batch
                )
                st.dataframe(result, use_container_width=True)
                st.caption("相同來源可重試；衝突檔案不會覆寫。請先預覽並確認來源網址。")
            except (OSError, ValueError, KeyError) as exc:
                st.error(f"批次清單無法處理：{exc}")
