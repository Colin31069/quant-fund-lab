"""Complete scenario reports; each successful account retains settings and business frames."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .types import ACCOUNT_FRAMES, MatchedSensitivity


def summary_frame(matched: MatchedSensitivity) -> pd.DataFrame:
    rows = []
    for row in matched.outcomes:
        record = row.to_dict()
        summaries = record.pop("summaries")
        record["undefined_metrics"] = ",".join(record["undefined_metrics"])
        rows.append({**record, **summaries})
    return pd.DataFrame(rows)


def export_matched_sensitivity(target: Path, matched: MatchedSensitivity) -> str:
    (target / "matched_sensitivity.json").write_text(
        json.dumps(matched.to_dict(), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False), encoding="utf-8")
    for row in matched.outcomes:
        if row.status != "succeeded":
            continue
        result = matched.accounts[(row.scenario.scenario_id, row.strategy)]
        for name in ACCOUNT_FRAMES:
            getattr(result, name).to_csv(target / f"{row.prefix}_{name}.csv", index=name == "equity_curve")
        (target / f"{row.prefix}_account.json").write_text(json.dumps(
            {"research": asdict(result.config), "execution": asdict(result.backtest_config)},
            ensure_ascii=False, sort_keys=True, allow_nan=False), encoding="utf-8")
    counts = pd.Series([row.status for row in matched.outcomes]).value_counts().to_dict()
    return ("<h2>策略與可交易基準敏感度</h2><p>全部情境在協議中固定；"
            "僅使用驗證期作診斷，不依結果回頭挑選成本或成交假設。"
            "ETF 沿用明列的稅率／限價假設；無成本參考另列。每個成功情境保留帳務與設定，"
            "失敗及受阻情境保留原因，沒有虛構績效。undefined_metrics 列出無定義的指標，"
            "零成交或已完成 episode 不足 30 筆不證明策略有效。</p>"
            + pd.DataFrame([counts]).to_html(index=False, escape=True))
