"""Deterministic decision tables and human-readable complete attempt-prefix disclosures."""
from __future__ import annotations

import html
from dataclasses import asdict

import pandas as pd

from .source_types import DecisionSource
from .types import ResearchDecision


def decision_tables(decision: ResearchDecision) -> tuple[pd.DataFrame, pd.DataFrame]:
    candidates, checks = [], []
    for row in decision.candidates:
        candidates.append({"candidate_id": row.candidate_id, "strategy": row.strategy, "status": row.status,
                           "development_score": row.development_score, "reasons": "; ".join(row.reasons)})
        checks.extend({"candidate_id": row.candidate_id, "strategy": row.strategy, **asdict(check)} for check in row.checks)
    return pd.DataFrame(candidates), pd.DataFrame(checks)


def render_decision(decision: ResearchDecision, sources: tuple[DecisionSource, ...], created_at: str) -> str:
    candidates, checks = decision_tables(decision)
    history = []
    for source in sources:
        if not source.attempts:
            history.append({"candidate_id": source.candidate_id, "attempt": None,
                            "status": "not_attempted", "reason": "no captured attempt"})
        for attempt in source.attempts:
            history.append({"candidate_id": source.candidate_id, "attempt": attempt.attempt,
                            "status": attempt.status, "reason": attempt.reason, "report": attempt.report_path})
    selected = f"{decision.selected_candidate or 'none'} / {decision.selected_strategy or 'none'}"
    return ("<!doctype html><html><head><meta charset='utf-8'><title>研究決策</title>"
        "<style>body{font-family:system-ui;margin:2em}table{border-collapse:collapse}"
        "th,td{padding:.4em;border:1px solid #ccc}</style></head><body><h1>凍結政策研究決策</h1>"
        "<p>產製時間：" + html.escape(created_at) + "<br>protocol：" + decision.protocol_id
        + "<br>decision：" + decision.decision_id + "<br>狀態：" + html.escape(decision.status)
        + "<br>開發期選定：" + html.escape(selected) + "</p>"
        "<p>只依開發期排名；驗證失敗、資料不足或情境失敗不改選另一候選。continue 僅表示繼續研究／觀察，"
        "不證明策略有效。2025 年後已接觸資料維持探索性，不參與排名或驗證門檻。"
        "本報告核對本機 registry 與來源內容，沒有外部簽章、獨立預註冊或市場資料真實性認證。"
        "保存的是明列的 attempt 歷史前綴；後來的新執行不改寫這份決策，也不表示它仍是最新狀態。</p>"
        "<h2>可執行政策</h2>" + pd.DataFrame([asdict(decision.policy)]).to_html(index=False, escape=True)
        + "<h2>全部候選</h2>" + candidates.to_html(index=False, escape=True)
        + "<h2>逐項檢查</h2>" + checks.to_html(index=False, escape=True)
        + "<h2>全部已捕捉嘗試（含失敗與受阻）</h2>" + pd.DataFrame(history).to_html(index=False, escape=True)
        + "</body></html>")
