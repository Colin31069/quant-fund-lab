"""Sidebar controls for persistent paper trading and verifiable research reports."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import streamlit as st


@dataclass(frozen=True)
class PaperLedgerInputs:
    """UI inputs for persistent paper trading and verification exports."""

    persist_paper_ledger: bool
    paper_ledger_path: Path
    paper_snapshot_root: Path
    paper_ledger_mode: str
    paper_confirm_rebuild: bool
    export_verifiable_report: bool


def render_paper_ledger_controls(odd_lot_study: bool) -> PaperLedgerInputs:
    """Render the persistent paper ledger and verifiable report sidebar controls."""
    st.markdown("**💾 虛擬帳本與審計**")
    persist_paper_ledger = st.checkbox(
        "啟用本機 persistent paper ledger", value=False, disabled=odd_lot_study
    )
    paper_ledger_path = Path("artifacts/paper_trading.sqlite")
    paper_snapshot_root = Path("artifacts/paper_snapshots")
    paper_ledger_mode = "continue"
    paper_confirm_rebuild = False
    if persist_paper_ledger:
        existing_paper_ledger = paper_ledger_path.is_file()
        paper_ledger_mode = st.radio(
            "虛擬帳本操作",
            ["continue", "rebuild"],
            index=0 if existing_paper_ledger else 1,
            format_func=lambda mode: (
                "安全續跑現有帳本（不得覆寫）"
                if mode == "continue"
                else "建立新帳本（可能覆寫原始交易紀錄）"
            ),
        )
        if paper_ledger_mode == "continue":
            st.caption(
                "續跑前核對舊交易日的價格、FX、目標權重、成交設定和 snapshot；"
                "不一致時停止，不會自動清除 SQLite。"
            )
        else:
            st.caption(
                "新建模式會重設 SQLite 並覆寫相同日期的 snapshots。"
                "若已有帳本，請先備份整個 artifacts/paper_trading.sqlite "
                "及 artifacts/paper_snapshots/。"
            )
            if existing_paper_ledger:
                paper_confirm_rebuild = st.checkbox(
                    "我已備份或明確接受既有虛擬交易紀錄被覆寫"
                )

    export_verifiable_report = st.checkbox("匯出可驗證研究報告", value=False)
    return PaperLedgerInputs(
        persist_paper_ledger=persist_paper_ledger,
        paper_ledger_path=paper_ledger_path,
        paper_snapshot_root=paper_snapshot_root,
        paper_ledger_mode=paper_ledger_mode,
        paper_confirm_rebuild=paper_confirm_rebuild,
        export_verifiable_report=export_verifiable_report,
    )
