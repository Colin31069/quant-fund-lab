"""Explicit forward-intent registration and virtual-account operations."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from ..odd_lot_inputs.types import PriceSourcePolicy
from .forward_workflow import run_observation_account
from .observation import load_observation_plan, register_forward_observation


def render_observation_panel(st, source_directory: str | Path) -> None:
    st.subheader("零股前向虛擬觀察")
    st.caption("先核驗已保存的研究決策，再註冊未來開始日。缺少完整新行情時保持等待或阻擋。")
    with st.form("observation_registration"):
        decision = st.text_input("已保存的分階段決策包", "")
        first = st.text_input("計畫開始交易日（YYYY-MM-DD）", "")
        access = st.text_area("歷史資料接觸與用途註記", "")
        registry = st.text_input("實驗登記庫", "artifacts/experiments/registry.sqlite")
        studies = st.text_input("研究封存根目錄", "artifacts/odd_lot_studies")
        output = st.text_input("前向計畫保存根目錄", "artifacts/odd_lot_observations")
        register = st.form_submit_button("核驗決策並註冊前向計畫")
    if register:
        try:
            path = register_forward_observation(decision, first_session=first, access_note=access,
                registry_path=registry,studies_directory=studies,source_directory=source_directory,
                output_directory=output)
            st.success("已註冊；等待可核驗的新交易日資料。")
            st.code(str(path))
        except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as exc:
            st.error(f"計畫註冊停止：{exc}")
    with st.form("observation_account"):
        plan = st.text_input("前向計畫目錄", "")
        through = st.text_input("觀察截止日（YYYY-MM-DD）", "")
        official = st.text_input("官方行情與事件資料包", "artifacts/twse_odd_lot")
        provider = st.text_input("供應商資料包（官方模式留空）", "")
        policy = st.text_area("供應商選源政策 JSON（官方模式留空）", "")
        account = st.text_input("前向帳戶 SQLite", "artifacts/odd_lot_observation/account.sqlite")
        snapshots = st.text_input("前向行情快照根目錄", "artifacts/odd_lot_observation/snapshots")
        archives = st.text_input("前向原始來源封存根目錄", "artifacts/odd_lot_observation/sources")
        mode = st.radio("前向帳戶操作", ["安全續跑既有前向帳戶", "建立全新前向帳戶"])
        read = st.form_submit_button("讀取前向計畫")
        run = st.form_submit_button("核驗資料並執行虛擬觀察")
    if read:
        try:
            st.json(asdict(load_observation_plan(plan)))
            st.caption("此處僅核對計畫內容指紋；執行時另認證決策、原始來源、快照與既有帳戶。")
        except (ValueError, TypeError, KeyError, OSError) as exc:
            st.error(f"無法讀取計畫：{exc}")
    if run:
        try:
            if not plan.strip() or not through.strip():
                raise ValueError("請提供前向計畫目錄與觀察截止日")
            values = json.loads(policy) if policy.strip() else None
            if values is not None:
                values["priority"] = tuple(values.get("priority", ("TWSE", "FinMind")))
            result = run_observation_account(plan,through=through,registry_path=registry,
                studies_directory=studies,source_directory=source_directory,official_directory=official,
                account_path=account,snapshot_root=snapshots,source_archive_root=archives,
                create=mode == "建立全新前向帳戶",provider_directory=provider.strip() or None,
                price_policy=PriceSourcePolicy(**values) if values is not None else None)
            if result.status == "active":
                st.success("資料核驗及虛擬帳戶操作完成。")
            elif result.status == "pending":
                st.info("尚未到計畫開始日，未啟用帳戶。")
            else:
                st.warning("資料尚未完整，觀察受阻；只保留已核驗完成的交易日。")
            st.json({"plan_id":result.plan_id,"status":result.status,"reasons":result.reasons})
            if result.replay is not None:
                st.caption(f"最後完成日：{result.replay.checkpoint.session}；新增 {result.replay.committed_sessions} 日。")
        except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as exc:
            st.error(f"前向觀察停止：{exc}")
