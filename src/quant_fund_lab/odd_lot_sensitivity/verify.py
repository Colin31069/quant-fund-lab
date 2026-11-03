"""Reconcile the complete frozen sensitivity grid with source accounts and their summaries."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ..analytics import performance_metrics
from ..odd_lot_benchmarks import BenchmarkSpec
from ..odd_lot_protocol.diagnostics import _read_frame
from ..odd_lot_protocol.sensitivity import declared_scenarios, sensitivity_enabled
from ..odd_lot_research import OddLotResearchConfig, OddLotResearchResult, odd_lot_backtest_config
from ..odd_lot_study import _backtest_config
from ..trade_analytics import summarize_episodes
from .engine import account_summaries, scenario_config
from .reporting import summary_frame
from .types import ACCOUNT_FRAMES, MatchedSensitivity, SensitivityOutcome


def verify_matched_report(directory: Path, metadata: dict, plan_json: str,
                          candidate_id: str, benchmark: BenchmarkSpec | None) -> None:
    manifest = json.loads((directory / "report_manifest.json").read_text(encoding="utf-8"))["files"]
    names = {name for name in manifest if name.startswith("scenario_")}
    path = directory / "matched_sensitivity.json"
    if not sensitivity_enabled(plan_json):
        if path.exists() or names:
            raise ValueError("matched sensitivity artifacts not declared by protocol")
        return
    if path.name not in manifest or benchmark is None:
        raise ValueError("matched sensitivity report or benchmark missing")
    raw = json.loads(path.read_text(encoding="utf-8"))
    scenarios = declared_scenarios(plan_json, candidate_id)
    strategies = ("ensemble", "momentum", benchmark.result_name)
    expected_keys = [(row.scenario_id, name) for row in scenarios for name in strategies]
    if [(row["scenario_id"], row["strategy"]) for row in raw["outcomes"]] != expected_keys:
        raise ValueError("sensitivity report omits or changes a frozen scenario")
    research = OddLotResearchConfig(**metadata["research_config"])
    base = _backtest_config(metadata["backtest_config"])
    execution = _read_frame(directory / "execution_summary.csv")
    available = set(zip(execution.period, execution.strategy)) if not execution.empty else set()
    decision = next(row for row in metadata["readiness"]["periods"] if row["period"] == "validation")
    unavailable = json.loads((directory / "unavailable.json").read_text(encoding="utf-8"))
    outcomes, accounts, expected_names = [], {}, set()
    for row, (scenario_id, strategy) in zip(raw["outcomes"], expected_keys):
        scenario = next(spec for spec in scenarios if spec.scenario_id == scenario_id)
        blocked = decision["status"] != "ready" or ("validation", strategy) not in available
        if blocked:
            reason = unavailable.get(f"validation/{strategy}", "required validation account or inputs are not ready")
            outcome = SensitivityOutcome(scenario, strategy, "blocked", reason)
        elif row["status"] == "failed":
            outcome = SensitivityOutcome(scenario, strategy, "failed", row["reason"])
        else:
            config = scenario_config(research, scenario, strategy, benchmark)
            backtest = odd_lot_backtest_config(base, config)
            prefix = f"scenario_{scenario_id}_{strategy}"
            account_name = prefix + "_account.json"
            expected_names.add(account_name)
            if account_name not in manifest or json.loads((directory / account_name).read_text(encoding="utf-8")) != {
                "research": asdict(config), "execution": asdict(backtest),
            }:
                raise ValueError("sensitivity account settings differ from frozen scenario")
            frames = {}
            for name in ACCOUNT_FRAMES:
                artifact = f"{prefix}_{name}.csv"
                expected_names.add(artifact)
                if artifact not in manifest:
                    raise ValueError("sensitivity account source absent from manifest")
                frames[name] = _read_frame(directory / artifact, curve=name == "equity_curve")
            required = {"equity", "cash", "sale_receivables", "receivable_value", "buy_payables", "sale_payables"}
            if len(frames["equity_curve"]) < 2 or not required.issubset(frames["equity_curve"].columns):
                raise ValueError("invalid sensitivity account equity source")
            reference = _read_frame(directory / f"validation_{strategy}_equity_curve.csv", curve=True)
            if not frames["equity_curve"].index.equals(reference.index):
                raise ValueError("sensitivity account sessions differ from primary account")
            summaries = account_summaries(frames["equity_curve"], frames["fills"], frames["orders"], frames["episodes"])
            outcome = SensitivityOutcome(scenario, strategy, "succeeded", "", summaries)
            accounts[(scenario_id, strategy)] = OddLotResearchResult(
                **frames, metrics=performance_metrics(frames["equity_curve"].equity),
                trade_summary=summarize_episodes(frames["episodes"]), config=config, backtest_config=backtest)
        if row != outcome.to_dict():
            raise ValueError("sensitivity outcome differs from source account or blocked inputs")
        outcomes.append(outcome)
    matched = MatchedSensitivity(scenarios, strategies, tuple(outcomes), accounts)
    if raw != matched.to_dict() or names != expected_names:
        raise ValueError("sensitivity report account inventory differs from declared outcomes")
    if "sensitivity.csv" not in manifest or (directory / "sensitivity.csv").read_bytes() != summary_frame(matched).to_csv(index=False).encode():
        raise ValueError("sensitivity CSV differs from source-account reconstruction")
