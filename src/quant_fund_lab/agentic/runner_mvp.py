"""Deterministic MVP Strategy Pipeline Runner for quant_fund_lab."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any

from quant_fund_lab.agentic.canary import run_canary_test
from quant_fund_lab.agentic.compiler import ASTSanitizer, CompiledAlphaStrategy
from quant_fund_lab.agentic.schemas import StrategyContract
from quant_fund_lab.analytics import performance_metrics
from quant_fund_lab.backtest import run_backtest
from quant_fund_lab.config import BacktestConfig
from quant_fund_lab.data import MarketData


def compute_provenance_hash(contract: StrategyContract, metrics: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash over canonical contract JSON and metrics JSON."""
    canonical_payload = {
        "contract": contract.model_dump(mode="json"),
        "metrics": {
            k: float(v) if isinstance(v, (int, float)) else v
            for k, v in sorted(metrics.items())
        },
    }
    canonical_json = json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def run_strategy_pipeline(
    contract: StrategyContract,
    data: MarketData,
    seed: int = 42,
    raise_on_error: bool = False,
    backtest_config: BacktestConfig | None = None,
) -> dict[str, Any]:
    """Execute end-to-end agentic strategy pipeline with pre-flight gates and provenance tracking.

    Execution Flow:
    1. Pre-Flight Gate 1 (AST Check):
       ASTSanitizer.validate_contract(contract)
    2. Compilation:
       strategy = CompiledAlphaStrategy.from_contract(contract)
    3. Pre-Flight Gate 2 (Canary Perturbation Test):
       run_canary_test(strategy, data, seed=seed)
    4. Deterministic Execution:
       Precompute clean panel cache and invoke run_backtest with custom_alpha_evaluator.
    5. Metrics & Provenance:
       Compute performance metrics and deterministic SHA-256 provenance hash.
    6. Return dictionary:
       {"status": "SUCCESS", "strategy_name": ..., "provenance_hash": ..., "metrics": ..., "equity_final": ...}
    """
    stage = "pre_flight_ast"
    try:
        # 1. Pre-Flight Gate 1 (AST Check)
        stage = "ast_validation"
        ASTSanitizer.validate_contract(contract)

        # 2. Compilation
        stage = "compilation"
        strategy = CompiledAlphaStrategy.from_contract(contract)

        # 3. Pre-Flight Gate 2 (Canary Perturbation Test)
        stage = "canary_test"
        run_canary_test(strategy, data, seed=seed)

        # 4. Deterministic Execution
        stage = "backtest"
        strategy.precompute_panel(data)
        if backtest_config is not None:
            config = dataclasses.replace(backtest_config, custom_alpha_evaluator=strategy)
        else:
            config = BacktestConfig(custom_alpha_evaluator=strategy)
        result = run_backtest(data, config)

        # 5. Metrics & Provenance
        stage = "metrics"
        equity_series = result.equity_curve["equity"]
        metrics = performance_metrics(equity_series)
        provenance_hash = compute_provenance_hash(contract, metrics)

        # 6. Return dictionary
        return {
            "status": "SUCCESS",
            "strategy_name": contract.strategy_name,
            "provenance_hash": provenance_hash,
            "metrics": metrics,
            "equity_final": float(equity_series.iloc[-1]),
        }
    except Exception as exc:
        if raise_on_error:
            raise
        return {
            "status": "FAILED",
            "strategy_name": getattr(contract, "strategy_name", "unknown"),
            "stage": stage,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


__all__ = [
    "compute_provenance_hash",
    "run_strategy_pipeline",
]
