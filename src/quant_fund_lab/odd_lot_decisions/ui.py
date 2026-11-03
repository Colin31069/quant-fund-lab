"""Read-only research browser; widget reruns cannot create protocols or attempts."""
from __future__ import annotations

import json
import sqlite3
import subprocess
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from ..odd_lot_protocol.decision import policy_from_plan
from ..odd_lot_protocol.provenance import capture_execution_identity
from .inspection import ResearchOverview, inspect_decision, inspect_research, inspect_selection
from .ui_actions import render_research_actions


def _overview(st, result: ResearchOverview, source_directory: str | Path) -> None:
    protocol = result.protocol
    st.caption(f"協議 ID：{protocol.protocol_id}")
    st.caption(f"凍結資料：{protocol.dataset_id}；執行身分：{protocol.execution.identity}")
    st.dataframe(pd.DataFrame([asdict(period) for period in protocol.periods]), use_container_width=True)
    policy = policy_from_plan(protocol.analysis_plan_json)
    if policy is None:
        st.info("舊協議未宣告可執行決策政策；只瀏覽既有研究，不套用預設門檻。")
    else:
        st.markdown("**已凍結決策政策**")
        st.json(asdict(policy))
    histories = dict(result.histories)
    candidates, attempts = [], []
    for candidate in protocol.candidates:
        history = histories[candidate.candidate_id]
        candidates.append({"candidate_id":candidate.candidate_id, "study_id":candidate.study_id,
            "attempt_count":len(history), "latest_status":history[-1].status if history else "not_attempted"})
        attempts.extend({"candidate_id":candidate.candidate_id, **asdict(attempt)} for attempt in history)
    st.markdown("**全部宣告候選**")
    st.dataframe(pd.DataFrame(candidates), use_container_width=True)
    st.markdown("**全部嘗試歷史（含失敗與受阻）**")
    if attempts:
        st.dataframe(pd.DataFrame(attempts), use_container_width=True)
    else:
        st.info("尚無嘗試紀錄；瀏覽不會建立 attempt。")
    with st.expander("凍結環境與分析規則"):
        frozen = json.loads(protocol.execution.environment_json)
        st.json(frozen)
        st.json(json.loads(protocol.analysis_plan_json))
        try:
            current = json.loads(capture_execution_identity(source_directory).environment_json)
            if current != frozen:
                st.warning("目前環境與凍結環境不同；來源重建可能拒絕。請用匹配環境核驗，不會自動切換或放寬守門。")
            else:
                st.caption("目前 runtime／依賴 profile 與凍結紀錄一致；這不代表目前程式與歷史執行身分相同。")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            st.warning(f"無法核對目前環境：{exc}")


def _selection(st, value: dict) -> None:
    st.markdown("**保存的開發期選擇**")
    st.write(f"狀態：{value['status']}；候選：{value['selected_candidate'] or '無'}；策略：{value['selected_strategy'] or '無'}")
    st.dataframe(pd.DataFrame(value["candidates"]), use_container_width=True)


def render_research_browser(st, source_directory: str | Path) -> None:
    st.subheader("零股研究協議與決策瀏覽")
    st.caption("瀏覽與重繪不啟動研究、不建立協議或 attempt。保存快照不代表目前最新結果；寫入需另按明確操作按鈕。")
    with st.form("odd_lot_research_browser"):
        protocol = st.text_input("研究協議目錄", "")
        registry = st.text_input("實驗登記 SQLite 路徑", "artifacts/odd_lot_experiments/registry.sqlite")
        studies = st.text_input("研究來源根目錄", "artifacts/odd_lot_studies")
        mode = st.selectbox("瀏覽內容", ["僅協議與歷史", "保存的開發選擇", "保存的決策"])
        artifact = st.text_input("保存產物目錄（選擇或決策）", "")
        read = st.form_submit_button("核驗並瀏覽研究")
    operations = st.checkbox("顯示凍結／執行操作", value=False)
    if not read and not operations:
        return
    try:
        if not protocol.strip():
            raise ValueError("請提供已凍結且已登記的研究協議目錄")
        overview = inspect_research(protocol, registry_path=registry)
        _overview(st, overview, source_directory)
        if operations:
            render_research_actions(st,overview,protocol,registry_path=registry,
                studies_directory=studies,source_directory=source_directory)
        if mode == "僅協議與歷史":
            return
        if not artifact.strip():
            raise ValueError("請提供保存的選擇或決策目錄；此頁不會建立新產物")
        if mode == "保存的開發選擇":
            saved = inspect_selection(protocol, artifact, registry_path=registry, studies_directory=studies)
            st.caption(f"selection ID：{saved.inputs.selection.selection_id}；capture：{saved.capture_fingerprint}")
            _selection(st, saved.inputs.selection.to_dict())
        else:
            saved = inspect_decision(protocol, artifact, registry_path=registry, studies_directory=studies)
            decision = json.loads(saved.decision_json)
            st.success("保存決策的來源重建核驗通過")
            st.write(f"決策狀態：{decision['status']}；固定候選：{decision['selected_candidate'] or '無'}")
            if saved.selection_json is not None:
                _selection(st, json.loads(saved.selection_json))
            st.dataframe(pd.DataFrame(decision["candidates"]), use_container_width=True)
            checks = [{"candidate_id":row["candidate_id"], "strategy":row["strategy"], **check}
                      for row in decision["candidates"] for check in row["checks"]]
            st.dataframe(pd.DataFrame(checks), use_container_width=True)
            st.caption("continue 僅表示按凍結規則繼續研究，不證明策略有效；歷史探索期不參與排名。")
            with st.expander("保存的來源前綴"):
                st.json(json.loads(saved.sources_json))
    except (OSError, ValueError, TypeError, KeyError, IndexError, sqlite3.Error) as exc:
        st.error(f"研究核驗停止：{exc}")
        st.caption("未建立新研究或改寫來源。請核對路徑、凍結環境與來源完整性，再重新讀取。")
