"""Every mutation requires its own explicit form submission, never a page rerun."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .actions import execute_frozen_candidate, freeze_policy_child, save_current_decision
from .inspection import ResearchOverview


def render_research_actions(st, overview: ResearchOverview, protocol_directory: str, *,
                              registry_path: str, studies_directory: str, source_directory: str | Path) -> None:
    st.caption("以下按鈕才會寫入：改政策另建子協議；執行只接受凍結候選；失敗／重試紀錄保留。")
    with st.form("freeze_research_policy"):
        policy = st.text_area("完整 DecisionPolicy JSON（所有欄位明列）", value="")
        protocols = st.text_input("新協議根目錄（須已有父協議）", "artifacts/odd_lot_protocols")
        freeze = st.form_submit_button("凍結新政策子協議")
    with st.form("run_frozen_research_candidate"):
        candidate = st.selectbox("已凍結候選 ID", [row.candidate_id for row in overview.protocol.candidates])
        execute = st.form_submit_button("執行已凍結候選")
    with st.form("publish_research_decision"):
        output = st.text_input("決策產物根目錄", "artifacts/odd_lot_decisions")
        publish = st.form_submit_button("保存開發選擇並產生決策")
    try:
        if freeze:
            if not policy.strip():
                raise ValueError("政策 JSON 不得留空；所有門檻與停用項目都須明列")
            result = freeze_policy_child(protocol_directory,policy,registry_path=registry_path,
                studies_directory=studies_directory,protocols_directory=protocols,source_directory=source_directory)
            st.success(f"新子協議已凍結：{result.directory}")
            st.caption("請改用新協議目錄核驗與執行；此動作沒有啟動候選搜尋。")
        if execute:
            result = execute_frozen_candidate(protocol_directory,candidate,registry_path=registry_path,
                studies_directory=studies_directory,source_directory=source_directory)
            st.success(f"候選執行完成；狀態：{result.attempt.status}；報告：{result.report}")
        if publish:
            result = save_current_decision(protocol_directory,registry_path=registry_path,
                studies_directory=studies_directory,output_directory=output,source_directory=source_directory)
            st.success(f"保存決策完成；狀態：{result.decision.status}；報告：{result.report}")
    except (OSError, ValueError, TypeError, KeyError, IndexError, sqlite3.Error) as exc:
        st.error(f"研究操作停止：{exc}")
        st.caption("保留已寫入的不可變協議／selection 及嘗試歷史；不自動重跑、改選或重設。")
