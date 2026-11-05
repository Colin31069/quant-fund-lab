"""Tests for Agentic Tournament Orchestrator."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_fund_lab.agentic.orchestrator import AgenticTournamentOrchestrator, TournamentResult
from quant_fund_lab.agentic.schemas import ExecutionOverlayConfig, PrimitiveConfig, StrategyContract
from quant_fund_lab.agentic.tournament import TemporalPartition
from quant_fund_lab.agentic.trials_registry import TrialsRegistry
from quant_fund_lab.data import MarketData


@pytest.fixture
def mock_market_data() -> MarketData:
    rng = np.random.default_rng(42)
    # 550 bars: enough for Warmup (100), IS (300), Embargo (50), OOS (100)
    dates = pd.date_range("2020-01-01", periods=550, freq="B")
    tickers = ["AAPL", "MSFT", "GOOGL", "AMZN"]
    n_dates, n_tickers = len(dates), len(tickers)

    ret = rng.normal(0.0005, 0.015, (n_dates, n_tickers))
    px = 100.0 * np.cumprod(1.0 + ret, axis=0)

    close_df = pd.DataFrame(px, index=dates, columns=tickers)
    open_df = close_df * (1.0 + rng.normal(0.0, 0.002, (n_dates, n_tickers)))
    volume_df = pd.DataFrame(rng.uniform(1e6, 5e6, (n_dates, n_tickers)), index=dates, columns=tickers)

    return MarketData(
        open=open_df,
        close=close_df,
        volume=volume_df,
    )


def test_agentic_orchestrator_e2e(tmp_path, mock_market_data: MarketData) -> None:
    db_path = tmp_path / "trials.db"
    registry = TrialsRegistry(db_path=db_path)

    # Custom partition suitable for 550 bars test data
    partition = TemporalPartition(
        warmup_bars=80,
        in_sample_bars=280,
        embargo_bars=40,
        oos_vault_bars=150,
    )

    archetype_signals = {
        "trend": "cs_zscore(kalman_fast)",
        "mean_reversion": "cs_demean(-ou_slow)",
    }

    def mock_generator(system_prompt: str, user_prompt: str) -> StrategyContract:
        # Determine archetype from user prompt
        arch = "mean_reversion" if "mean_reversion" in user_prompt else "trend"
        sig = archetype_signals[arch]
        prim = (
            PrimitiveConfig(primitive_id="ou_slow", module_type="OUMeanReversion", params={"half_life": 10})
            if arch == "mean_reversion"
            else PrimitiveConfig(primitive_id="kalman_fast", module_type="KalmanTrend", params={"lookback": 15})
        )

        return StrategyContract(
            strategy_name=f"test_{arch}_alpha",
            agent_archetype=arch,  # type: ignore[arg-type]
            economic_hypothesis=(
                f"Statistical {arch} premium exploiting structural inefficiencies in multi-day price momentum. "
                "This hypothesis satisfies the minimum length requirement for validation."
            ),
            market_universe="US_LIQUID_500",
            primitives=[prim],
            signal_expression=sig,
            regime_gate_expression="where(vol_21d > 0.0, 1.0, 0.0)",
            execution_overlay=ExecutionOverlayConfig(
                rebalance_frequency="1W",
                trade_buffer_delta_weight=0.01,
                max_single_position_weight=0.20,
                target_gross_leverage=1.0,
                odd_lot_execution_mode="avoid_odd_lots",
            ),
        )

    orchestrator = AgenticTournamentOrchestrator(
        registry=registry,
        partition=partition,
        archetypes=["trend", "mean_reversion"],
        max_rounds_per_lineage=2,
        seed=42,
    )

    result = orchestrator.run(mock_market_data, mock_generator)

    assert isinstance(result, TournamentResult)
    assert len(result.lineages) == 2
    assert "trend" in result.lineages
    assert "mean_reversion" in result.lineages
    assert len(result.skeptic_verdicts) == 2
    assert result.provenance_manifest["run_id"] == result.run_id
    assert registry.count_trials() >= 2


def test_agentic_orchestrator_rejection(tmp_path, mock_market_data: MarketData) -> None:
    db_path = tmp_path / "trials_reject.db"
    registry = TrialsRegistry(db_path=db_path)

    partition = TemporalPartition(
        warmup_bars=80,
        in_sample_bars=280,
        embargo_bars=40,
        oos_vault_bars=150,
    )

    def failing_generator(system_prompt: str, user_prompt: str) -> StrategyContract:
        # Generate an empty/non-functional alpha that fails friction gate
        return StrategyContract(
            strategy_name="failing_alpha",
            agent_archetype="trend",
            economic_hypothesis=(
                "Failing strategy deliberately designed to test rejection handling under friction. "
                "Ensuring hypothesis exceeds the 80 character boundary threshold."
            ),
            market_universe="US_LIQUID_500",
            primitives=[
                PrimitiveConfig(primitive_id="kalman_fast", module_type="KalmanTrend", params={"lookback": 15})
            ],
            # Constant 0 signal will have 0 return / negative net sharpe under friction
            signal_expression="where(kalman_fast > 0.0, 0.0, 0.0)",
            regime_gate_expression="where(vol_21d > 0.0, 1.0, 0.0)",
            execution_overlay=ExecutionOverlayConfig(
                rebalance_frequency="1D",
                trade_buffer_delta_weight=0.0,
                max_single_position_weight=0.20,
                target_gross_leverage=1.0,
                odd_lot_execution_mode="avoid_odd_lots",
            ),
        )

    orchestrator = AgenticTournamentOrchestrator(
        registry=registry,
        partition=partition,
        archetypes=["trend"],
        max_rounds_per_lineage=1,
    )

    result = orchestrator.run(mock_market_data, failing_generator)
    assert len(result.approved_strategies) == 0
    assert result.tournament_ensemble["status"] == "EMPTY"
