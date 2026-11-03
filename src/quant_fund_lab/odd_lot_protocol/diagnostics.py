"""Versioned diagnostic declaration, report export and source-account reconciliation."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from ..odd_lot_diagnostics import diagnose_odd_lot_account, inputs_from_result
from ..odd_lot_diagnostics.types import (
    DIAGNOSTICS_RULE,
    OddLotDiagnostics,
    RiskDiagnosticInputs,
    StudyRiskDiagnostics,
)
from .types import json_object

if TYPE_CHECKING:
    from ..odd_lot_study import OddLotStudyResult


def diagnostics_enabled(plan_json: str) -> bool:
    plan = json_object(plan_json)
    if plan.get("engine") in {"frozen_odd_lot_batch_v1", "frozen_odd_lot_batch_v2"}:
        if "risk_diagnostics" in plan:
            raise ValueError("legacy analysis plan cannot declare risk diagnostics")
        return False
    if plan.get("engine") in {f"frozen_odd_lot_batch_v{version}" for version in range(3, 7)} and plan.get("risk_diagnostics") == DIAGNOSTICS_RULE:
        return True
    raise ValueError("unsupported protocol diagnostic plan")


def add_risk_diagnostics(study: OddLotStudyResult) -> OddLotStudyResult:
    """Only diagnose actual accounts; blocked periods remain explicitly unavailable."""
    diagnostics = StudyRiskDiagnostics(
        {key: diagnose_odd_lot_account(inputs_from_result(result)) for key, result in study.results.items()},
        dict(study.unavailable))
    return replace(study, risk_diagnostics=diagnostics)


def _frames(result: OddLotDiagnostics) -> dict[str, pd.DataFrame]:
    return {"capital_utilization": result.capital, "episode_risk_audit": result.episode_frame,
            "unfilled_order_summary": result.unfilled_orders}


def export_risk_diagnostics(target: Path, diagnostics: StudyRiskDiagnostics) -> str:
    """Return escaped HTML and write machine-readable evidence before manifest hashing."""
    payload = diagnostics.to_dict()
    (target / "risk_diagnostics.json").write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False), encoding="utf-8")
    summary = []
    for (period, strategy), result in sorted(diagnostics.accounts.items()):
        for name, frame in _frames(result).items():
            frame.to_csv(target / f"{period}_{strategy}_{name}.csv", index=False)
        summary.append({"period": period, "strategy": strategy, "closed_episodes": result.closed_count,
                        "sample_sufficient": result.to_dict()["sample_sufficient"],
                        "source_issues": "; ".join(result.source_issues)})
    return ("<h2>風險診斷</h2><p>建倉預算由成交證據核對；未平倉或待收權利款不算已實現虧損。"
            "止損延遲按模擬 sessions 計算，未退出列 pending。未結算應付款比例是交割負擔，"
            "與資產配置比例重疊；NAV 非正或來源不足列 unavailable。"
            "30 筆已完成 episode 只作樣本數提示，不證明策略有效。</p>"
            + (pd.DataFrame(summary).to_html(index=False, escape=True) if summary
               else "<p>沒有可計算診斷的帳戶；受阻期間與原因見不可用清單。</p>"))


def _read_frame(path: Path, *, curve: bool = False) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path, float_precision="round_trip", keep_default_na=False,
                            na_values=[""])
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    if curve:
        frame = frame.set_index(frame.columns[0])
        frame.index = pd.to_datetime(frame.index)
    return frame


def verify_diagnostic_report(directory: Path, metadata: dict, plan_json: str, benchmark_name: str | None) -> None:
    """Reconstruct diagnostic values from archived source frames, without rerunning trades."""
    enabled = diagnostics_enabled(plan_json)
    path = directory / "risk_diagnostics.json"
    if not enabled:
        if path.exists():
            raise ValueError("diagnostics were not declared by this protocol")
        return
    manifest = json.loads((directory / "report_manifest.json").read_text(encoding="utf-8"))["files"]
    if path.name not in manifest:
        raise ValueError("diagnostics missing from report manifest")
    execution = _read_frame(directory / "execution_summary.csv")
    accounts, prefixes = {}, set()
    if not execution.empty and not {"period", "strategy"}.issubset(execution.columns):
        raise ValueError("invalid diagnostic account binding")
    for row in execution.itertuples(index=False):
        period, strategy = str(row.period), str(row.strategy)
        if period not in metadata["periods"] or strategy not in {"ensemble", "momentum", "equal_weight", benchmark_name}:
            raise ValueError("diagnostic account differs from protocol")
        key, prefix = (period, strategy), f"{period}_{strategy}"
        if key in accounts:
            raise ValueError("duplicate diagnostic account")
        prefixes.add(prefix + "_equity_curve.csv")
        frames = {}
        for name in ("equity_curve", "fills", "orders", "signals", "episodes", "corporate_actions", "terminal_events"):
            source = f"{prefix}_{name}.csv"
            if source not in manifest:
                raise ValueError("diagnostic source missing from manifest")
            frames[name] = _read_frame(directory / source, curve=name == "equity_curve")
        inputs = RiskDiagnosticInputs(**frames,
            strategy="equal_weight" if strategy == benchmark_name else strategy,
            configured_risk_budget=metadata["research_config"]["risk_budget"])
        result = diagnose_odd_lot_account(inputs)
        accounts[key] = result
        for name, frame in _frames(result).items():
            artifact = f"{prefix}_{name}.csv"
            if artifact not in manifest or (directory / artifact).read_bytes() != frame.to_csv(index=False).encode():
                raise ValueError("diagnostic CSV differs from source-account reconstruction")
    source_curves = {name for name in manifest if name.endswith("_equity_curve.csv")}
    if json_object(plan_json).get("engine") in {"frozen_odd_lot_batch_v4", "frozen_odd_lot_batch_v5", "frozen_odd_lot_batch_v6"}:
        source_curves = {name for name in source_curves if not name.startswith("scenario_")}
    if prefixes != source_curves:
        raise ValueError("diagnostic account inventory differs from archived accounts")
    unavailable = json.loads((directory / "unavailable.json").read_text(encoding="utf-8"))
    expected = StudyRiskDiagnostics(accounts, unavailable).to_dict()
    if json.loads(path.read_text(encoding="utf-8")) != expected:
        raise ValueError("diagnostics differ from source-account reconstruction")
