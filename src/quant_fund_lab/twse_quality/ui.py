"""Presentation of the frozen decision, without a second set of readiness rules."""
from __future__ import annotations

import pandas as pd

from .repairs import repair_summary_frame


def render_readiness(st, readiness: dict, readiness_fingerprint: str) -> None:
    """Display and export the exact decision already validated by the research runner."""
    st.subheader("正式研究就緒狀態")
    st.caption(f"就緒判定指紋：{readiness_fingerprint}")
    rows = []
    for period in readiness["periods"]:
        rows.append({"period": period["period"], "start": period["start"], "end": period["end"],
                     "status": period["status"], "warmup_required": period["warmup"]["required"],
                     "warmup_verified": len(period["warmup"]["verified_sessions"]),
                     "blocking_count": len(period["blocking_ids"])})
    st.dataframe(pd.DataFrame(rows), use_container_width=True)
    findings = pd.DataFrame(readiness["findings"])
    if not findings.empty:
        affected = {finding["finding_id"]: [] for finding in readiness["findings"]}
        for period in readiness["periods"]:
            for key in period["blocking_ids"]:
                affected[key].append(period["period"])
        findings["affected_periods"] = findings.finding_id.map(lambda key: ",".join(affected[key]))
        st.download_button("下載研究修復清單", findings.to_csv(index=False).encode("utf-8-sig"),
                           file_name="study_readiness_findings.csv", mime="text/csv")
        with st.expander("正式判定、原始問題與佐證"):
            only_blockers = st.checkbox("僅顯示本研究受阻項目", value=True)
            displayed = findings[findings.affected_periods.ne("")] if only_blockers else findings
            st.dataframe(displayed, use_container_width=True)
            st.caption("完整下載保留原官方問題、來源政策及適用說明；顯示篩選不改變正式判定。")
    st.caption("匯入或修正資料後請重新執行研究，產生新判定；舊研究保留原始來源與紀錄。")
    repairs = repair_summary_frame(readiness)
    st.subheader("分期缺月與暖機依賴")
    st.caption("缺月按標的與月份去重；期內與暖機可引用同一來源，計數不相加。空白表示暖機窗口無法確認。")
    st.dataframe(repairs.drop(columns=["period_source_keys", "warmup_source_keys"]), use_container_width=True)
    st.download_button("下載分期修復摘要", repairs.to_csv(index=False).encode("utf-8-sig"),
                       file_name="readiness_repairs.csv", mime="text/csv")
