"""Unit and integration tests for MVP agentic strategy pipeline runner."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from quant_fund_lab.agentic.canary import LookAheadError
from quant_fund_lab.agentic.compiler import ASTSanitizer
from quant_fund_lab.agentic.runner_mvp import (
    compute_provenance_hash,
    run_strategy_pipeline,
)
from quant_fund_lab.agentic.schemas import (
    ExecutionOverlayConfig,
    PrimitiveConfig,
    StrategyContract,
)
from quant_fund_lab.data import MarketData, synthetic_market_data


@pytest.fixture
def runner_market_data() -> MarketData:
    """Fixture providing at least 200 bars for canary warmup and backtest."""
    return synthetic_market_data(
        symbols=("AAPL", "MSFT", "GOOG", "AMZN"),
        periods=200,
        seed=42,
    )


@pytest.fixture
def valid_trend_contract() -> StrategyContract:
    """Fixture providing a valid trend-following strategy contract."""
    return StrategyContract(
        strategy_name="kalman_trend_decay",
        agent_archetype="trend",
        economic_hypothesis=(
            "Medium-term Kalman filter extracts low-frequency trend signals from daily prices, "
            "which are smoothed using linear time-series decay to mitigate microstructure noise."
        ),
        market_universe="US_LIQUID_500",
        primitives=[
            PrimitiveConfig(
                primitive_id="k_trend",
                module_type="KalmanTrend",
                params={"half_life": 10},
            )
        ],
        signal_expression="ts_decay_linear(cs_rank(k_trend), 5)",
        regime_gate_expression="clip(1.0 - mkt_vol_pct_252d, 0.0, 1.0)",
        execution_overlay=ExecutionOverlayConfig(
            rebalance_frequency="1D",
            trade_buffer_delta_weight=0.01,
            max_single_position_weight=0.2,
            target_gross_leverage=0.8,
            odd_lot_execution_mode="avoid_odd_lots",
        ),
    )


def test_ast_sanitizer_validate_contract(valid_trend_contract: StrategyContract) -> None:
    """Verify ASTSanitizer.validate_contract returns True for valid contract."""
    assert ASTSanitizer.validate_contract(valid_trend_contract) is True


def test_pipeline_valid_strategy_end_to_end(
    runner_market_data: MarketData,
    valid_trend_contract: StrategyContract,
) -> None:
    """Test full successful execution of a valid strategy contract through pipeline."""
    result = run_strategy_pipeline(valid_trend_contract, runner_market_data, seed=42)

    assert result["status"] == "SUCCESS"
    assert result["strategy_name"] == "kalman_trend_decay"
    assert isinstance(result["provenance_hash"], str)
    assert len(result["provenance_hash"]) == 64

    metrics = result["metrics"]
    assert "total_return" in metrics
    assert "sharpe" in metrics
    assert "annual_volatility" in metrics
    assert "max_drawdown" in metrics

    assert result["equity_final"] > 0.0


def test_invalid_ast_contract_blocked_at_preflight(
    runner_market_data: MarketData,
    valid_trend_contract: StrategyContract,
) -> None:
    """Verify invalid AST expression (e.g. eval) is caught at Gate 1 and never enters backtest."""
    invalid_contract = valid_trend_contract.model_copy(
        update={"signal_expression": "eval(1)"}
    )

    with patch("quant_fund_lab.agentic.runner_mvp.run_backtest") as mock_backtest:
        result = run_strategy_pipeline(invalid_contract, runner_market_data)
        mock_backtest.assert_not_called()

    assert result["status"] == "FAILED"
    assert result["stage"] == "ast_validation"
    assert "whitelist" in result["error"]

    with pytest.raises(ValueError, match="whitelist"):
        run_strategy_pipeline(invalid_contract, runner_market_data, raise_on_error=True)


def test_lookahead_leak_blocked_at_canary_gate(
    runner_market_data: MarketData,
    valid_trend_contract: StrategyContract,
) -> None:
    """Verify canary test detects lookahead and halts pipeline before run_backtest."""
    with patch(
        "quant_fund_lab.agentic.runner_mvp.run_canary_test",
        side_effect=LookAheadError("Simulated future leakage"),
    ), patch("quant_fund_lab.agentic.runner_mvp.run_backtest") as mock_backtest:
        result = run_strategy_pipeline(valid_trend_contract, runner_market_data)
        mock_backtest.assert_not_called()

    assert result["status"] == "FAILED"
    assert result["stage"] == "canary_test"
    assert result["error_type"] == "LookAheadError"
    assert "Simulated future leakage" in result["error"]

    with patch(
        "quant_fund_lab.agentic.runner_mvp.run_canary_test",
        side_effect=LookAheadError("Simulated future leakage"),
    ), pytest.raises(LookAheadError, match="Simulated future leakage"):
        run_strategy_pipeline(valid_trend_contract, runner_market_data, raise_on_error=True)


def test_inactive_strategy_blocked_by_canary(
    runner_market_data: MarketData,
    valid_trend_contract: StrategyContract,
) -> None:
    """Verify inactive strategy is rejected by canary gate before backtest."""
    inactive_contract = valid_trend_contract.model_copy(
        update={"signal_expression": "0.0 * cs_rank(k_trend)"}
    )

    with patch("quant_fund_lab.agentic.runner_mvp.run_backtest") as mock_backtest:
        result = run_strategy_pipeline(inactive_contract, runner_market_data)
        mock_backtest.assert_not_called()

    assert result["status"] == "FAILED"
    assert result["stage"] == "canary_test"
    assert "inactive" in result["error"].lower()


def test_provenance_hash_deterministic(
    runner_market_data: MarketData,
    valid_trend_contract: StrategyContract,
) -> None:
    """Verify provenance hash is strictly deterministic for identical inputs and sensitive to changes."""
    res1 = run_strategy_pipeline(valid_trend_contract, runner_market_data, seed=42)
    res2 = run_strategy_pipeline(valid_trend_contract, runner_market_data, seed=42)

    assert res1["provenance_hash"] == res2["provenance_hash"]
    assert res1["equity_final"] == res2["equity_final"]
    assert res1["metrics"] == res2["metrics"]

    # Sensitivity: contract change alters hash
    mod_contract = valid_trend_contract.model_copy(
        update={"strategy_name": "kalman_trend_decay_variant"}
    )
    h_mod = compute_provenance_hash(mod_contract, res1["metrics"])
    assert h_mod != res1["provenance_hash"]

    # Sensitivity: metric change alters hash
    mod_metrics = dict(res1["metrics"])
    mod_metrics["sharpe"] = mod_metrics["sharpe"] + 0.1
    h_metric_mod = compute_provenance_hash(valid_trend_contract, mod_metrics)
    assert h_metric_mod != res1["provenance_hash"]
