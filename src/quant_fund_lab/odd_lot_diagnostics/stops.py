"""Trace emitted stop signals to share liquidation, separately from entitlement settlement."""
from __future__ import annotations

import pandas as pd

from .types import RiskDiagnosticInputs


def _exit_evidence(inputs: RiskDiagnosticInputs, symbol: str, date: pd.Timestamp) -> bool:
    for frame, criteria in (
        (inputs.fills, {"side": "SELL"}),
        (inputs.terminal_events, {}),
        (inputs.corporate_actions, {"action": "stock_split", "quantity_after": 0}),
    ):
        if frame.empty or not {"timestamp", "symbol", *criteria}.issubset(frame.columns):
            continue
        match = frame.symbol.eq(symbol) & pd.to_datetime(frame.timestamp, errors="coerce").eq(date)
        for name, value in criteria.items():
            match &= frame[name].eq(value)
        if match.any():
            return True
    return False


def stop_audit(inputs: RiskDiagnosticInputs, symbol: str, entry: pd.Timestamp,
               exit_date: pd.Timestamp | None) -> tuple[dict, str]:
    output = {"first_stop_signal": None, "share_exit": exit_date.isoformat() if exit_date is not None else None,
              "stop_attempts": None, "stop_delay_sessions": None, "stop_delay_calendar_days": None,
              "observed_sessions_since_stop": None, "stop_status": "unavailable"}
    if inputs.strategy == "equal_weight":
        output["stop_status"] = "not_applicable"
        return output, ""
    dates = pd.DatetimeIndex(inputs.equity_curve.index)
    if dates.empty or dates.hasnans or dates.has_duplicates or not dates.is_monotonic_increasing:
        return output, "invalid simulation session sequence"
    if exit_date is not None and pd.isna(exit_date):
        output["share_exit"] = None
        return output, "invalid share-exit date"
    signals = inputs.signals
    required = {"timestamp", "symbol", "reason"}
    if not signals.empty and not required.issubset(signals.columns):
        return output, "missing stop signal source columns"
    def in_episode(frame: pd.DataFrame) -> pd.Series:
        timestamps = pd.to_datetime(frame.timestamp)
        return frame.symbol.eq(symbol) & timestamps.ge(entry) & (
            timestamps.le(exit_date) if exit_date is not None else timestamps.le(dates[-1]))
    attempts = inputs.orders
    if not attempts.empty and not {"timestamp", "symbol", "side", "reason"}.issubset(attempts.columns):
        return output, "missing stop order source columns"
    for frame in (signals, attempts):
        if not frame.empty and not pd.to_datetime(frame.timestamp, errors="coerce").isin(dates).all():
            return output, "signal or order date outside simulation sessions"
    attempted = (attempts.loc[in_episode(attempts) & attempts.side.eq("SELL") & attempts.reason.eq("stop")]
                 if not attempts.empty else attempts)
    triggered = signals
    if not signals.empty:
        mask = in_episode(signals) & signals.reason.eq("stop")
        if exit_date is not None:
            mask &= pd.to_datetime(signals.timestamp).lt(exit_date)
        triggered = signals.loc[mask]
    if triggered.empty:
        stop_fills = inputs.fills
        fill_evidence = (not stop_fills.empty and required.issubset(stop_fills.columns)
                         and (in_episode(stop_fills) & stop_fills.reason.eq("stop")).any())
        if not attempted.empty or fill_evidence:
            return output, "stop execution without recorded trigger"
        output.update(stop_status="not_triggered", stop_attempts=0)
        return output, ""
    first = pd.Timestamp(pd.to_datetime(triggered.timestamp).min())
    output["first_stop_signal"] = first.isoformat()
    if first not in dates or entry not in dates:
        return output, "stop or entry date outside simulation sessions"
    if not attempted.empty and pd.to_datetime(attempted.timestamp).le(first).any():
        return output, "stop order precedes next-session eligibility"
    output["stop_attempts"] = len(attempted)
    if exit_date is None:
        output.update(stop_status="pending", observed_sessions_since_stop=int((dates > first).sum()))
    elif exit_date not in dates or not _exit_evidence(inputs, symbol, exit_date):
        return output, "missing share-exit evidence or simulation session"
    else:
        output.update(stop_status="completed", stop_delay_sessions=int(((dates > first) & (dates <= exit_date)).sum()),
                      stop_delay_calendar_days=(exit_date - first).days)
    return output, ""
