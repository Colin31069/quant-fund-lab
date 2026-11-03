"""Audit entry-budget evidence and realized episode losses without using open marks."""
from __future__ import annotations

import hashlib
import json
import math

import pandas as pd

from .stops import stop_audit
from .types import EpisodeRiskAudit, RiskDiagnosticInputs


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _budget(inputs: RiskDiagnosticInputs, symbol: str, entry: pd.Timestamp) -> tuple[float | None, str]:
    fills = inputs.fills
    required = {"timestamp", "symbol", "side", "entry_risk_budget"}
    if not required.issubset(fills.columns):
        return None, "missing entry-budget fill evidence"
    matches = fills.loc[fills.symbol.eq(symbol) & fills.side.eq("BUY") & pd.to_datetime(fills.timestamp, errors="coerce").eq(entry)]
    if len(matches) != 1:
        return None, "entry-budget evidence is missing or ambiguous"
    budget = _finite(matches.iloc[0].entry_risk_budget)
    configured = _finite(inputs.configured_risk_budget)
    if budget is None or budget <= 0:
        return None, "invalid entry-budget evidence"
    if configured is None or budget != configured:
        return None, "entry budget differs from frozen configuration"
    return budget, ""


def episode_risk_audits(inputs: RiskDiagnosticInputs) -> tuple[tuple[EpisodeRiskAudit, ...], tuple[str, ...]]:
    required = {"symbol", "entry", "exit", "status", "quantity", "pending_receivables", "pnl", "planned_risk"}
    if not required.issubset(inputs.episodes.columns):
        return (), ("missing episode source columns: " + ",".join(sorted(required - set(inputs.episodes.columns))),)
    rows, issues, seen = [], [], set()
    for row in inputs.episodes.itertuples(index=False):
        symbol, entry = str(row.symbol), pd.to_datetime(row.entry, errors="coerce")
        exit_date = pd.to_datetime(row.exit, errors="coerce") if pd.notna(row.exit) else None
        key = json.dumps([symbol, entry.isoformat()], ensure_ascii=True)
        if pd.isna(entry) or key in seen:
            issues.append("invalid or duplicate episode identity: " + key)
            continue
        seen.add(key)
        quantity, pending = _finite(row.quantity), _finite(row.pending_receivables)
        valid_state = (quantity is not None and quantity >= 0 and quantity.is_integer()
                       and pending is not None and pending >= 0 and pending.is_integer()
                       and row.status in {"closed", "open"}
                       and (row.status == "closed") == (quantity == 0 and pending == 0)
                       and (quantity == 0) == (exit_date is not None)
                       and (exit_date is None or pd.notna(exit_date))
                       and (exit_date is None or exit_date >= entry))
        budget, reason = (None, "") if inputs.strategy == "equal_weight" else _budget(inputs, symbol, entry)
        loss = max(0.0, -_finite(row.pnl)) if valid_state and row.status == "closed" and _finite(row.pnl) is not None else None
        status = "not_applicable" if inputs.strategy == "equal_weight" else "available"
        if not valid_state:
            status, reason = "unavailable", "inconsistent episode position/entitlement state"
        elif row.status == "closed" and loss is None:
            status, reason = "unavailable", "nonfinite closed-episode net P&L"
        elif reason:
            status = "unavailable"
        elif inputs.strategy != "equal_weight" and row.status != "closed":
            status, reason = "pending", "position or cash entitlement remains open"
        excess = max(0.0, loss - budget) if status == "available" else None
        ratio = loss / budget if status == "available" else None
        if ratio is not None and not math.isfinite(ratio):
            status, reason, excess, ratio = "unavailable", "nonfinite loss-to-budget calculation", None, None
        stop, stop_issue = stop_audit(inputs, symbol, entry, exit_date)
        if not valid_state:
            stop["stop_status"] = "unavailable"
        for issue in (reason if status == "unavailable" else "", stop_issue):
            if issue:
                issues.append(symbol + "/" + entry.isoformat() + ": " + issue)
        rows.append(EpisodeRiskAudit(
            episode_id=hashlib.sha256(key.encode()).hexdigest(), symbol=symbol, entry=entry.isoformat(),
            episode_status=str(row.status), pending_receivables=int(pending) if pending is not None and pending >= 0 and pending.is_integer() else None,
            entry_risk_budget=budget, estimated_entry_risk=_finite(row.planned_risk),
            realized_net_loss=loss, loss_over_budget=excess, loss_to_budget_ratio=ratio,
            risk_status=status, risk_reason=reason, **stop))
    return tuple(rows), tuple(issues)
