"""Explicit read-only combined-rights account inspection with shared audit gates."""
import sqlite3
from dataclasses import asdict

from .catalog_inspection import inspect_rights_catalog


def render_rights_inspection(st) -> None:
    st.subheader("權利事件帳戶核驗")
    st.caption("讀取已封存的虛擬帳戶，核對固定請求、獨立 NAV／風險與歷史重播。")
    with st.form("rights_readonly_catalog_inspection"):
        account = st.text_input("權利帳戶 SQLite 路徑", "")
        catalog = st.text_input("權利請求目錄檔案", "")
        checksum = st.text_input("外部保存的目錄 SHA-256", "")
        requests = st.text_input("封存每日請求資料夾", "")
        read = st.form_submit_button("唯讀核驗權利帳戶")
    if not read:
        return
    try:
        if not all(value.strip() for value in (account, catalog, checksum, requests)):
            raise ValueError("請提供既有帳戶、目錄檔案、外部 checksum 與每日請求資料夾")
        result = inspect_rights_catalog(account.strip(), catalog.strip(),
            expected_catalog_sha256=checksum.strip(), requests_directory=requests.strip())
        st.success("本機封存核驗通過：獨立 NAV、風險及原請求重播已核對。")
        st.info("來源公告時點與正式協議仍須另行認證；此結果不代表真實事件或前向觀察已啟用。")
        st.metric("已完成交易日", result.completed_sessions)
        st.metric("目錄待處理日", result.pending_catalog_sessions)
        st.metric("可用現金（TWD）", result.cash)
        st.metric("帳戶淨值（TWD）", result.nav if result.nav is not None else "尚無完成日")
        st.json(asdict(result))
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        st.error(f"權利帳戶核驗停止：{exc}")
