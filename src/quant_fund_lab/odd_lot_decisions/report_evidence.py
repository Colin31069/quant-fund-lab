"""Derive decision metrics from verified account CSVs and locked archive settings."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd

from ..analytics import performance_metrics
from ..odd_lot_diagnostics import diagnose_odd_lot_account
from ..odd_lot_diagnostics.types import RiskDiagnosticInputs
from ..odd_lot_protocol.benchmark import benchmark_from_plan
from ..odd_lot_protocol.build import verify_candidate_binding
from ..odd_lot_protocol.diagnostics import _read_frame
from ..odd_lot_protocol.storage import load_protocol
from ..odd_lot_protocol.types import (
    ExperimentAttempt,
    ExperimentRecord,
    StudyProtocol,
    canonical_json,
)
from ..odd_lot_research import OddLotResearchConfig, odd_lot_backtest_config
from ..odd_lot_sensitivity.engine import account_summaries
from ..odd_lot_sensitivity.types import ACCOUNT_FRAMES
from ..odd_lot_study import _backtest_config, load_frozen_odd_lot_study, verify_odd_lot_study_report
from .types import STRATEGIES, CandidateEvidence, PeriodEvidence, ScenarioEvidence, fingerprint


def checked_report(report: Path, studies: Path, protocol: StudyProtocol,
                   record: ExperimentRecord, attempt: ExperimentAttempt) -> str:
    expected = (studies / record.study_id / "reports").resolve()
    if report.is_symlink() or report.resolve().parent != expected:
        raise ValueError("decision report is outside its declared frozen study")
    if not verify_odd_lot_study_report(report) or load_protocol(report) != protocol:
        raise ValueError("decision source report verification failed")
    context = json.loads((report / "experiment.json").read_text(encoding="utf-8"))
    if (context["experiment"] != asdict(record) or context["attempt"] != attempt.attempt
            or context["numerical_result_fingerprint"] != attempt.result_fingerprint):
        raise ValueError("decision source report differs from registered attempt")
    return json.loads((report / "report_manifest.json").read_text(encoding="utf-8"))["report_id"]


def _settings(report: Path, metadata: dict, period: str, strategy: str, protocol: StudyProtocol) -> None:
    research = OddLotResearchConfig(**metadata["research_config"])
    benchmark = benchmark_from_plan(protocol.analysis_plan_json)
    if strategy == benchmark.result_name:
        research = replace(research, strategy="equal_weight", max_positions=1, max_weight=1.0,
                           instrument_rules={benchmark.symbol: benchmark.instrument_rule})
    else:
        research = replace(research, strategy=strategy)
    expected = {"research": asdict(research),
                "execution": asdict(odd_lot_backtest_config(_backtest_config(metadata["backtest_config"]), research))}
    with closing(sqlite3.connect((report / "study_ledger.sqlite").resolve().as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT study_id,dataset_id,settings_json,settings_sha256 FROM accounts WHERE account_id=?",
                         (f"{period}/{strategy}",)).fetchone()
    if (row is None or row[0] != metadata["study_id"] or row[1] != metadata["dataset_id"]
            or row[2] != canonical_json(expected) or hashlib.sha256(row[2].encode()).hexdigest() != row[3]):
        raise ValueError("decision source account settings differ from frozen candidate")


def _period(report: Path, metadata: dict, dates: pd.DatetimeIndex, period: str,
             strategy: str, protocol: StudyProtocol) -> PeriodEvidence:
    decision = next(row for row in metadata["readiness"]["periods"] if row["period"] == period)
    if decision["status"] != "ready":
        return PeriodEvidence("blocked", f"{period} frozen readiness is {decision['status']}")
    prefix = f"{period}_{strategy}"
    manifest = json.loads((report / "report_manifest.json").read_text(encoding="utf-8"))["files"]
    if prefix + "_equity_curve.csv" not in manifest:
        unavailable = json.loads((report / "unavailable.json").read_text(encoding="utf-8"))
        return PeriodEvidence("unavailable", unavailable.get(f"{period}/{strategy}", "required account was not computed"))
    _settings(report, metadata, period, strategy, protocol)
    frames = {name: _read_frame(report / f"{prefix}_{name}.csv", curve=name == "equity_curve") for name in ACCOUNT_FRAMES}
    start, end = metadata["periods"][period]
    first, last = int(dates.searchsorted(pd.Timestamp(start), side="left")), int(dates.searchsorted(pd.Timestamp(end), side="right"))
    if first < 1 or not frames["equity_curve"].index.equals(dates[first-1:last]):
        raise ValueError("decision account sessions differ from the frozen evaluation period")
    if frames["equity_curve"].equity.iloc[0] != metadata["backtest_config"]["initial_cash"]:
        raise ValueError("decision account initial capital differs from frozen input")
    benchmark = benchmark_from_plan(protocol.analysis_plan_json)
    audit = diagnose_odd_lot_account(RiskDiagnosticInputs(
        **{name: frame for name, frame in frames.items() if name != "settlements"},
        strategy="equal_weight" if strategy == benchmark.result_name else strategy,
        configured_risk_budget=metadata["research_config"]["risk_budget"]))
    if audit.source_issues:
        return PeriodEvidence("unavailable", "; ".join(audit.source_issues))
    metrics = performance_metrics(frames["equity_curve"].equity)
    comparison = _read_frame(report / "comparison.csv")
    reported = comparison.loc[comparison.period.eq(period) & comparison.strategy.eq(strategy)]
    if len(reported) != 1:
        raise ValueError("decision source comparison does not identify one primary account")
    for key, value in metrics.items():
        actual = reported.iloc[0].get(key)
        if not (pd.isna(actual) and not math.isfinite(value)) and (
            not isinstance(actual, (int, float)) or not math.isfinite(actual)
            or not math.isclose(float(actual), value, rel_tol=1e-12, abs_tol=1e-12)
        ):
            raise ValueError("decision source comparison differs from account NAV")
    if reported.iloc[0].get("closed_count") != audit.closed_count:
        raise ValueError("decision source completed-episode count differs from account evidence")
    values = {key: float(value) if math.isfinite(value) else None for key, value in metrics.items()}
    rows = audit.episode_risk
    ratios = [row.loss_to_budget_ratio for row in rows if row.loss_to_budget_ratio is not None]
    delays = [row.stop_delay_sessions for row in rows if row.stop_delay_sessions is not None]
    known_stops = all(row.stop_status != "unavailable" for row in rows)
    return PeriodEvidence("available", completed_episodes=audit.closed_count,
        **{key: values[key] for key in ("annual_return", "total_return", "max_drawdown", "annual_volatility", "sharpe", "calmar")},
        risk_evidence_complete=all(row.risk_status == "available" for row in rows) and known_stops,
        maximum_loss_to_budget_ratio=max(ratios) if ratios else None,
        maximum_stop_delay_sessions=max(delays, default=0) if known_stops else None,
        pending_stop_episodes=sum(row.stop_status == "pending" for row in rows) if known_stops else None)


def report_candidate_evidence(report: Path, studies: Path, protocol: StudyProtocol,
                               record: ExperimentRecord, attempt: ExperimentAttempt,
                               *, strategies: tuple[str, ...] = STRATEGIES) -> tuple[CandidateEvidence, ...]:
    if (not isinstance(strategies, tuple) or not strategies or len(set(strategies)) != len(strategies)
            or not set(strategies).issubset(STRATEGIES)):
        raise ValueError("decision evidence requires declared active strategies")
    data, metadata = load_frozen_odd_lot_study(studies / record.study_id)
    candidate = next(row for row in protocol.candidates if row.candidate_id == record.candidate_id)
    verify_candidate_binding(protocol, candidate, metadata)
    benchmark = benchmark_from_plan(protocol.analysis_plan_json)
    matched = json.loads((report / "matched_sensitivity.json").read_text(encoding="utf-8"))
    comparator = _period(report, metadata, data.close.index, "validation", benchmark.result_name, protocol)
    proof = fingerprint([protocol.protocol_id, record.experiment_id, attempt.result_fingerprint])
    rows = []
    for strategy in strategies:
        scenarios = []
        for row in matched["outcomes"]:
            if row["strategy"] != strategy:
                continue
            peers = [peer for peer in matched["outcomes"] if peer["scenario_id"] == row["scenario_id"]
                     and peer["status"] != "succeeded"]
            if row["status"] == "succeeded" and peers:
                # A successful strategy row cannot certify an incomplete matched
                # execution. Development ranking stays independent of this gate.
                status = "failed" if any(peer["status"] == "failed" for peer in peers) else "blocked"
                reason = "; ".join(f"{peer['strategy']}: {peer['status']} {peer['reason']}" for peer in peers)
                evidence = PeriodEvidence(status, "required matched scenario counterpart unavailable: " + reason)
            elif row["status"] != "succeeded":
                evidence = PeriodEvidence(row["status"], row["reason"])
            else:
                prefix = f"scenario_{row['scenario_id']}_{strategy}"
                frames = {name: _read_frame(report / f"{prefix}_{name}.csv", curve=name == "equity_curve")
                          for name in ("equity_curve", "fills", "orders", "episodes")}
                values = json.loads(account_summaries(frames["equity_curve"], frames["fills"], frames["orders"], frames["episodes"]))
                evidence = PeriodEvidence("available", completed_episodes=values["closed_count"], **{
                    key: values[key] for key in ("annual_return", "total_return", "max_drawdown", "annual_volatility", "sharpe", "calmar")})
            scenarios.append(ScenarioEvidence(row["scenario_id"], evidence))
        rows.append(CandidateEvidence(record.candidate_id, strategy,
            _period(report, metadata, data.close.index, "development", strategy, protocol),
            _period(report, metadata, data.close.index, "validation", strategy, protocol),
            comparator, tuple(scenarios), proof))
    return tuple(rows)
