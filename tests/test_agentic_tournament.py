"""Unit tests for tournament ensemble, correlation clustering, and DriftedSleeveBook netting."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_fund_lab.agentic.schemas import (
    ExecutionOverlayConfig,
    PrimitiveConfig,
    StrategyContract,
)
from quant_fund_lab.agentic.tournament import (
    DriftedSleeveBook,
    TemporalPartition,
    compute_hrp_weights,
    prune_correlated_strategies,
)


@pytest.fixture
def mock_contracts() -> dict[str, StrategyContract]:
    c_trend = StrategyContract(
        strategy_name="trend_1w",
        agent_archetype="trend",
        economic_hypothesis=(
            "Persistent trend signals filtered by linear decay on intermediate lookback windows "
            "to capture steady institutional momentum and avoid noise."
        ),
        market_universe="US_LIQUID_500",
        primitives=[
            PrimitiveConfig(
                primitive_id="k1",
                module_type="KalmanTrend",
                params={"half_life": 10},
            )
        ],
        signal_expression="cs_rank(k1)",
        execution_overlay=ExecutionOverlayConfig(
            rebalance_frequency="1W",
            trade_buffer_delta_weight=0.01,
            max_single_position_weight=0.2,
            target_gross_leverage=0.8,
            odd_lot_execution_mode="avoid_odd_lots",
        ),
    )
    c_mr = StrategyContract(
        strategy_name="mr_1d",
        agent_archetype="mean_reversion",
        economic_hypothesis=(
            "Short-term price dislocations revert rapidly within 5 to 10 trading sessions "
            "when liquidity conditions allow mean reversion to manifest."
        ),
        market_universe="US_LIQUID_500",
        primitives=[
            PrimitiveConfig(
                primitive_id="ou1",
                module_type="OUMeanReversion",
                params={"lookback": 21},
            )
        ],
        signal_expression="-cs_rank(ou1)",
        execution_overlay=ExecutionOverlayConfig(
            rebalance_frequency="1D",
            trade_buffer_delta_weight=0.01,
            max_single_position_weight=0.2,
            target_gross_leverage=0.8,
            odd_lot_execution_mode="avoid_odd_lots",
        ),
    )
    return {"trend_1w": c_trend, "mr_1d": c_mr}


def test_temporal_partition() -> None:
    tp = TemporalPartition()
    assert tp.warmup_start == "2016-01-01"
    assert tp.is_start == "2017-01-01"
    assert tp.embargo_start == "2023-07-01"
    assert tp.oos_start == "2024-01-01"


def test_prune_correlated_strategies() -> None:
    # Construct 3 strategies: A, B (corr = 0.95 with A), C (corr = 0.10 with A)
    rng = np.random.default_rng(42)
    s_a = rng.normal(0.001, 0.01, 200)
    s_b = s_a + rng.normal(0, 0.001, 200)  # High correlation with A
    s_c = rng.normal(0.0005, 0.01, 200)  # Low correlation with A

    df = pd.DataFrame({"strat_a": s_a, "strat_b": s_b, "strat_c": s_c})
    # B has higher fitness than A
    fitness = {"strat_a": 1.2, "strat_b": 1.8, "strat_c": 1.1}

    survivors = prune_correlated_strategies(df, fitness, threshold=0.65)
    # Strat B should survive (higher fitness than A), Strat A eliminated, Strat C preserved
    assert "strat_b" in survivors
    assert "strat_c" in survivors
    assert "strat_a" not in survivors


def test_compute_hrp_weights() -> None:
    df = pd.DataFrame({
        "low_vol": np.random.normal(0.001, 0.005, 100),
        "high_vol": np.random.normal(0.001, 0.020, 100),
    })
    dsr = {"low_vol": 0.95, "high_vol": 0.90}
    weights = compute_hrp_weights(df, dsr)
    assert weights["low_vol"] > weights["high_vol"]
    assert sum(weights.values()) == pytest.approx(1.0)


def test_drifted_sleeve_book_netting(mock_contracts: dict[str, StrategyContract]) -> None:
    symbols = ("AAPL", "MSFT")
    strategy_weights = {"trend_1w": 0.5, "mr_1d": 0.5}

    book = DriftedSleeveBook(
        contracts=mock_contracts,
        strategy_weights=strategy_weights,
        symbols=symbols,
    )

    # Initial state: both sleeves hold 0
    stock_returns = np.array([0.01, -0.01])

    # Day 1: Trend wants to buy AAPL (+0.2, 0.0), MR wants to sell AAPL (-0.2, 0.0)
    # Internal netting cancels opposing trade!
    raw_signals = {
        "trend_1w": np.array([0.2, 0.0]),
        "mr_1d": np.array([-0.2, 0.0]),
    }

    target_weights, net_delta = book.update_and_rebalance(
        stock_returns=stock_returns,
        raw_signals=raw_signals,
    )

    # Opposing weights on AAPL (0.5 * 0.2 + 0.5 * -0.2 = 0.0) net out to zero!
    assert target_weights[0] == pytest.approx(0.0, abs=1e-6)
    assert net_delta[0] == pytest.approx(0.0, abs=1e-6)

    # Day 2: Trend is off-cycle (1W = every 5 days). MR rebalances daily.
    # Trend sleeve delta should be zero.
    raw_signals_d2 = {
        "trend_1w": np.array([0.5, 0.0]),  # Won't execute because off-cycle
        "mr_1d": np.array([0.0, 0.2]),
    }
    target_weights_d2, _ = book.update_and_rebalance(
        stock_returns=np.array([0.0, 0.0]),
        raw_signals=raw_signals_d2,
    )
    # Trend stayed at previous weight (0.2, 0.0), MR changed to (0.0, 0.2)
    assert target_weights_d2[0] == pytest.approx(0.5 * 0.2 + 0.5 * 0.0, abs=1e-6)
    assert target_weights_d2[1] == pytest.approx(0.5 * 0.0 + 0.5 * 0.2, abs=1e-6)
