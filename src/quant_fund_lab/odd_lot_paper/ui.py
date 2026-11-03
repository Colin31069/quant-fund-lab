"""Explicit historical account operations using the shared authenticated backend."""
from __future__ import annotations

import sqlite3
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .inspection import inspect_account
from .rebuild import rebuild_registered_account
from .workflow import replay_registered_account


def render_account_panel(st, source_directory: str | Path) -> None:
    st.subheader("零股持久化歷史帳戶")
    st.caption("僅使用凍結協議的虛擬歷史重播。前向觀察需另外啟用；不連接券商。")
    with st.form("odd_lot_account_form"):
        account = st.text_input("零股帳戶 SQLite 路徑", "artifacts/odd_lot_paper/account/ledger.sqlite")
        protocol = st.text_input("凍結協議目錄", "")
        candidate = st.text_input("候選 ID", "")
        studies = st.text_input("凍結研究根目錄", "artifacts/odd_lot_studies")
        snapshots = st.text_input("帳戶快照根目錄", "artifacts/odd_lot_paper/account/snapshots")
        period = st.selectbox("凍結期間", ["development", "validation", "historical_evaluation"])
        strategy = st.selectbox("凍結策略", ["ensemble", "momentum", "equal_weight"])
        cutoff = st.text_input("重播截止日（留空使用凍結期間終日）", "")
        mode = st.radio("帳戶操作", ["安全續跑既有帳戶", "建立全新帳戶"])
        target = st.text_input("重建目的帳戶（必須為新路徑）", "")
        st.caption("重建會重新核驗相同協議與設定，寫入另一個新帳戶；目前帳戶保留。")
        read = st.form_submit_button("核驗並讀取帳戶")
        run = st.form_submit_button("執行凍結歷史重播")
        rebuild = st.form_submit_button("保留原帳戶並重建至新路徑")
    if rebuild:
        try:
            if not protocol.strip() or not candidate.strip() or not target.strip():
                raise ValueError("重建需要凍結協議、候選 ID 與另一個全新帳戶路徑")
            rebuilt = rebuild_registered_account(account,target,protocol,candidate,
                period=period,strategy=strategy,studies_directory=studies,source_directory=source_directory,
                snapshot_root=snapshots,through=cutoff.strip() or None)
            st.success("重建完成；原帳戶保留。")
            st.json({"source_account":rebuilt.source_account,"target_account":rebuilt.target_account,
                     "parent_completion_digest":rebuilt.parent_completion_digest,
                     "source_files_sha256":rebuilt.source_files_sha256})
            account, read = target, True
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
            st.error(f"重建停止：{exc}")
    if run:
        try:
            if not protocol.strip() or not candidate.strip():
                raise ValueError("請提供已凍結的協議目錄與候選 ID")
            result = replay_registered_account(protocol, candidate, period=period, strategy=strategy,
                studies_directory=studies, source_directory=source_directory, account_path=account,
                snapshot_root=snapshots, create=mode == "建立全新帳戶", through=cutoff.strip() or None)
            st.success(f"完成；新增 {result.committed_sessions} 個交易日。")
            read = True
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
            st.error(f"帳戶操作停止：{exc}")
    if read:
        try:
            result = inspect_account(account)
            st.caption(f"最後完成日：{result.checkpoint.session}；完成指紋：{result.completion_digest}")
            st.caption("本次唯讀檢查核對結構、事件鏈與財務／風險生命週期；行情來源／快照由執行重播時另行核驗。")
            st.metric("已提交交易日", result.committed_sessions)
            st.metric("可支用現金（TWD）", f"{result.checkpoint.cash:,.2f}")
            if result.audit.passed:
                st.success("帳務與風險狀態稽核通過")
            else:
                st.error("稽核未通過；請依問題處理後重新核驗")
                st.dataframe(pd.DataFrame({"issue":result.audit.issues}))
            st.dataframe(pd.DataFrame(result.events, columns=["事件類別", "筆數"]))
            st.json(asdict(result.checkpoint))
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
            st.error(f"無法讀取帳戶：{exc}")
