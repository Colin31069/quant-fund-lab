"""Unit tests for iterative strategy reflection loop and persona prompt templates."""

from __future__ import annotations

import pytest

from quant_fund_lab.agentic.personas import COMMON_DSL_SPEC, PERSONA_PROMPTS
from quant_fund_lab.agentic.reflection_loop import (
    ReflectionResult,
    run_reflection_loop,
)
from quant_fund_lab.agentic.schemas import (
    ExecutionOverlayConfig,
    PrimitiveConfig,
    StrategyContract,
)
from quant_fund_lab.agentic.trials_registry import TrialsRegistry
from quant_fund_lab.data import MarketData, synthetic_market_data


@pytest.fixture
def test_market_data() -> MarketData:
    return synthetic_market_data(
        symbols=("AAPL", "MSFT", "GOOG"),
        periods=200,
        seed=101,
    )


def test_persona_prompts_structure() -> None:
    assert len(PERSONA_PROMPTS) == 4
    for archetype in ("trend", "mean_reversion", "quality_fundamental", "low_beta_defensive"):
        prompt = PERSONA_PROMPTS[archetype]
        assert "OUTPUT CONTRACT" in prompt
        assert archetype in prompt.lower() or "researcher" in prompt.lower()
    assert "ALLOWED CAUSAL OPERATORS" in COMMON_DSL_SPEC


def test_reflection_loop_early_stopping(test_market_data: MarketData) -> None:
    registry = TrialsRegistry(":memory:")
    call_count = [0]

    def mock_generator(system_prompt: str, user_prompt: str) -> StrategyContract:
        call_count[0] += 1
        # Each round, make the strategy progressively worse (e.g., lower leverage, higher buffer)
        lev = max(0.1, 0.8 - call_count[0] * 0.2)
        return StrategyContract(
            strategy_name=f"mock_trend_r{call_count[0]}",
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
            signal_expression="ts_decay_linear(cs_rank(k1), 5)",
            execution_overlay=ExecutionOverlayConfig(
                rebalance_frequency="1D",
                trade_buffer_delta_weight=0.01 * call_count[0],
                max_single_position_weight=0.2,
                target_gross_leverage=lev,
                odd_lot_execution_mode="avoid_odd_lots",
            ),
        )

    result = run_reflection_loop(
        generator=mock_generator,
        data=test_market_data,
        archetype="trend",
        registry=registry,
        max_rounds=4,
    )

    assert isinstance(result, ReflectionResult)
    # Stagnates on round 2 and 3, so early stops at or before round 3
    assert result.early_stopped is True
    assert result.status == "EARLY_STOPPED"
    assert result.rounds_completed <= 3
    assert len(result.history) == result.rounds_completed


def test_reflection_loop_handles_invalid_contract(test_market_data: MarketData) -> None:
    registry = TrialsRegistry(":memory:")

    # Invalid contract: banned function
    invalid_contract = StrategyContract(
        strategy_name="invalid_ast",
        agent_archetype="trend",
        economic_hypothesis=(
            "Testing error resilience and defensive filtering in the reflection loop "
            "for invalid AST tokens and unwhitelisted functions."
        ),
        market_universe="US_LIQUID_500",
        primitives=[
            PrimitiveConfig(
                primitive_id="k1",
                module_type="KalmanTrend",
                params={"half_life": 10},
            )
        ],
        signal_expression="banned_function(k1)",
        execution_overlay=ExecutionOverlayConfig(
            rebalance_frequency="1D",
            trade_buffer_delta_weight=0.01,
            max_single_position_weight=0.2,
            target_gross_leverage=0.8,
            odd_lot_execution_mode="avoid_odd_lots",
        ),
    )

    def mock_invalid_generator(system_prompt: str, user_prompt: str) -> StrategyContract:
        return invalid_contract

    result = run_reflection_loop(
        generator=mock_invalid_generator,
        data=test_market_data,
        archetype="trend",
        registry=registry,
        max_rounds=2,
    )

    assert result.early_stopped is True
    assert result.status == "EARLY_STOPPED"
    assert result.history[0]["status"] == "FAILED"
