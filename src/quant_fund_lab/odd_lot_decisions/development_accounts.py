"""Rebuild only development accounts, cross-checking their independent SQLite archive."""
from __future__ import annotations

import hashlib
import math
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

from ..analytics import performance_metrics
from ..odd_lot_diagnostics import diagnose_odd_lot_account
from ..odd_lot_diagnostics.types import RiskDiagnosticInputs
from ..odd_lot_protocol.diagnostics import _read_frame
from ..odd_lot_protocol.results import _frame
from ..odd_lot_protocol.types import StudyProtocol
from ..odd_lot_sensitivity.types import ACCOUNT_FRAMES
from .development_types import DevelopmentEvidence
from .report_evidence import _settings
from .types import fingerprint


def _cell(value: object) -> object:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T]00:00:00)?", value):
        return pd.Timestamp(value).isoformat()
    return value


def _check_archive(report: Path, strategy: str, frames: dict[str, pd.DataFrame]) -> None:
    """Compare this account only; neither query nor deserialize validation account rows."""
    with closing(sqlite3.connect((report / "study_ledger.sqlite").resolve().as_uri() + "?mode=ro", uri=True)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name in ACCOUNT_FRAMES:
            csv_frame = frames[name].reset_index() if name == "equity_curve" else frames[name]
            archived = (pd.read_sql_query(f'SELECT * FROM "{name}" WHERE account_id=?', db,
                        params=(f"development/{strategy}",)).drop(columns="account_id")
                        if name in tables else pd.DataFrame())
            if len(archived) != len(csv_frame):
                raise ValueError("development CSV row count differs from account archive")
            if csv_frame.empty:
                continue
            if name == "equity_curve" and archived.columns[0] != csv_frame.columns[0]:
                archived = archived.rename(columns={archived.columns[0]: csv_frame.columns[0]})
            if (not set(csv_frame.columns).issubset(archived.columns)
                    or any(archived[column].notna().any() for column in archived.columns.difference(csv_frame.columns))):
                raise ValueError("development CSV columns differ from account archive")
            for column in csv_frame.columns:
                if [_cell(v) for v in archived[column]] != [_cell(v) for v in csv_frame[column]]:
                    raise ValueError(f"development CSV values differ from account archive: {name}/{column}")


def development_account(report: Path, metadata: dict, dates: pd.DatetimeIndex, strategy: str,
                        protocol: StudyProtocol, dependency_fingerprint: str,
                        files: set[str]) -> DevelopmentEvidence:
    """Do not read comparison, scenario outcomes, risk summaries, or other periods."""
    candidate_id = next(row.candidate_id for row in protocol.candidates if row.study_id == metadata["study_id"])
    readiness = next(row for row in metadata["readiness"]["periods"] if row["period"] == "development")
    base = {"candidate_id": candidate_id, "strategy": strategy, "source_fingerprint": dependency_fingerprint}
    if readiness["status"] != "ready":
        return DevelopmentEvidence(**base, status="blocked", reason="development frozen readiness is " + readiness["status"])
    prefix = "development_" + strategy
    expected = {f"{prefix}_{name}.csv" for name in ACCOUNT_FRAMES}
    if not expected.issubset(files):
        base["source_fingerprint"] = fingerprint({"dependencies": dependency_fingerprint,
            "missing": sorted(expected - files), "available": {
                name: hashlib.sha256((report / name).read_bytes()).hexdigest() for name in sorted(expected & files)}})
        return DevelopmentEvidence(**base, status="unavailable", reason="required development account files missing")
    _settings(report, metadata, "development", strategy, protocol)
    frames = {name: _read_frame(report / f"{prefix}_{name}.csv", curve=name == "equity_curve") for name in ACCOUNT_FRAMES}
    _check_archive(report, strategy, frames)
    curve = frames["equity_curve"]
    start, end = metadata["periods"]["development"]
    first, last = int(dates.searchsorted(pd.Timestamp(start))), int(dates.searchsorted(pd.Timestamp(end), side="right"))
    if first < 1 or not curve.index.equals(dates[first - 1:last]):
        raise ValueError("development account sessions differ from frozen evaluation period")
    if curve.equity.iloc[0] != metadata["backtest_config"]["initial_cash"]:
        raise ValueError("development account capital differs from frozen input")
    proof = fingerprint({"dependencies": dependency_fingerprint,
                         "accounts": {name: _frame(frame) for name, frame in frames.items()}})
    base["source_fingerprint"] = proof
    audit = diagnose_odd_lot_account(RiskDiagnosticInputs(
        **{name: frame for name, frame in frames.items() if name != "settlements"},
        strategy=strategy, configured_risk_budget=metadata["research_config"]["risk_budget"]))
    if audit.source_issues:
        return DevelopmentEvidence(**base, status="unavailable", reason="; ".join(audit.source_issues))
    metrics = performance_metrics(curve.equity)
    return DevelopmentEvidence(**base, status="available", completed_episodes=audit.closed_count,
        **{key: float(metrics[key]) if math.isfinite(metrics[key]) else None for key in (
            "annual_return", "max_drawdown", "annual_volatility", "sharpe", "calmar")})
