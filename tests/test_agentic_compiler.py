"""Unit tests for AST compiler, PointInTimeView, CompiledAlphaStrategy, and Canary test."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_fund_lab.agentic.canary import (
    LookAheadError,
    compute_max_warmup_bars,
    run_canary_test,
)
from quant_fund_lab.agentic.compiler import (
    STATE_FEATURE_NAMES,
    ASTSanitizer,
    CompiledAlphaStrategy,
    PointInTimeView,
)
from quant_fund_lab.agentic.schemas import (
    ExecutionOverlayConfig,
    PrimitiveConfig,
    StrategyContract,
)
from quant_fund_lab.data import MarketData


@pytest.fixture
def sample_market_data() -> MarketData:
    n_bars = 220
    dates = pd.date_range("2023-01-01", periods=n_bars, freq="B")
    tickers = ["AAPL", "MSFT", "GOOG", "AMZN"]
    rng = np.random.default_rng(42)

    # Generate synthetic geometric random walk prices
    ret = rng.normal(0.0005, 0.015, size=(n_bars, len(tickers)))
    prices = 100.0 * np.exp(np.cumsum(ret, axis=0))
    volumes = rng.uniform(500_000, 2_000_000, size=(n_bars, len(tickers)))

    df_close = pd.DataFrame(prices, index=dates, columns=tickers)
    df_open = df_close * rng.uniform(0.99, 1.01, size=(n_bars, len(tickers)))
    df_volume = pd.DataFrame(volumes, index=dates, columns=tickers)

    return MarketData(
        open=df_open,
        close=df_close,
        volume=df_volume,
        base_currency="USD",
        exchange="NASDAQ",
    )


@pytest.fixture
def sample_contract() -> StrategyContract:
    return StrategyContract(
        strategy_name="test_trend_mean_reversion",
        agent_archetype="trend",
        economic_hypothesis=(
            "Medium-term Kalman trend captures persistent institutional drift while "
            "short-term overextended moves mean-revert to equilibrium value."
        ),
        market_universe="US_LIQUID_500",
        primitives=[
            PrimitiveConfig(
                primitive_id="k_fast",
                module_type="KalmanTrend",
                params={"half_life": 10},
            ),
            PrimitiveConfig(
                primitive_id="ou_slow",
                module_type="OUMeanReversion",
                params={"lookback": 60},
            ),
        ],
        signal_expression="cs_rank(k_fast) - cs_rank(ou_slow)",
        regime_gate_expression="clip(1.0 - mkt_vol_pct_252d, 0.0, 1.0)",
        execution_overlay=ExecutionOverlayConfig(
            rebalance_frequency="1D",
            trade_buffer_delta_weight=0.01,
            max_single_position_weight=0.15,
            target_gross_leverage=0.8,
            odd_lot_execution_mode="avoid_odd_lots",
        ),
    )


def test_ast_sanitizer_accepts_valid_expressions() -> None:
    valid_expressions = [
        "cs_rank(k_fast) - cs_rank(ou_slow)",
        "clip(cs_rank(k_fast), -0.5, 0.5)",
        "ts_mean(k_fast, 21)",
        "where(vol_21d > 0.25, cs_rank(k_fast), cs_rank(ou_slow))",
        "sign(ts_delta(k_fast, 5))",
    ]
    for expr in valid_expressions:
        code = ASTSanitizer.compile(expr)
        assert code is not None


def test_ast_sanitizer_bans() -> None:
    # 1. Imports
    with pytest.raises(ValueError, match="forbidden"):
        ASTSanitizer.validate("import os; cs_rank(x)")

    # 2. Attribute access
    with pytest.raises(ValueError, match="Attribute access is forbidden"):
        ASTSanitizer.validate("k_fast.shift(1)")
    with pytest.raises(ValueError, match="Attribute access is forbidden"):
        ASTSanitizer.validate("x.__class__")

    # 3. Subscripts
    with pytest.raises(ValueError, match="Subscript/slicing is forbidden"):
        ASTSanitizer.validate("k_fast[0]")

    # 4. String/date literals
    with pytest.raises(ValueError, match="String/date literals are forbidden"):
        ASTSanitizer.validate("cs_rank(x) + '2024-01-01'")

    # 5. Unknown function
    with pytest.raises(ValueError, match="not in the operator whitelist"):
        ASTSanitizer.validate("unknown_operator(x)")
    with pytest.raises(ValueError, match="not in the operator whitelist"):
        ASTSanitizer.validate("eval(x)")

    # 6. Non-canonical lookback
    with pytest.raises(ValueError, match="CANONICAL_LOOKBACKS"):
        ASTSanitizer.validate("ts_mean(x, 17)")

    # 7. Max depth exceeded (> 4)
    with pytest.raises(ValueError, match="exceeds maximum allowed depth"):
        ASTSanitizer.validate("clip(where(ts_mean(ts_delta(x, 5), 10) > 0, 1.0, 0.0), -1.0, 1.0)")

    # 8. Distinct primitive names exceeded (> 3)
    with pytest.raises(ValueError, match="distinct primitive names"):
        ASTSanitizer.validate("where(p1 > p2, p3, p4)")

    # 9. Allowed names violation
    with pytest.raises(ValueError, match="not in allowed primitives"):
        ASTSanitizer.validate("cs_rank(p1)", allowed_names={"p2", "p3"})


def test_point_in_time_view(sample_market_data: MarketData, sample_contract: StrategyContract) -> None:
    view = PointInTimeView(sample_market_data, sample_contract.primitives)
    # Primitives evaluated and present in namespace
    assert "k_fast" in view.namespace
    assert "ou_slow" in view.namespace
    assert isinstance(view.namespace["k_fast"], pd.DataFrame)
    assert view.namespace["k_fast"].shape == sample_market_data.close.shape

    # All stationary state features present
    for feat in STATE_FEATURE_NAMES:
        assert feat in view.namespace, f"Missing feature: {feat}"
        assert view.namespace[feat].shape == sample_market_data.close.shape
        assert np.isfinite(view.namespace[feat].to_numpy()).all()

    # Tradable mask
    assert view.tradable_mask.shape == sample_market_data.close.shape
    assert view.tradable_mask.all().all()


def test_compiled_alpha_strategy_weights(sample_market_data: MarketData, sample_contract: StrategyContract) -> None:
    strategy = CompiledAlphaStrategy(sample_contract)
    weights = strategy.precompute_panel(sample_market_data)

    assert isinstance(weights, pd.DataFrame)
    assert weights.shape == sample_market_data.close.shape
    assert np.isfinite(weights.to_numpy()).all()

    # Gross leverage normalized to target <= 0.8
    gross_lev = weights.abs().sum(axis=1)
    assert (gross_lev <= sample_contract.execution_overlay.target_gross_leverage + 1e-6).all()

    # Position clipping: max single position <= 0.15
    max_w = sample_contract.execution_overlay.max_single_position_weight
    assert (weights.abs() <= max_w + 1e-6).all().all()

    # Call interface
    dt = sample_market_data.close.index[100]
    w_series = strategy(sample_market_data, dt)
    assert isinstance(w_series, pd.Series)
    pd.testing.assert_series_equal(w_series, weights.loc[dt])


def test_canary_warmup_calculation(sample_contract: StrategyContract) -> None:
    # k_fast: half_life=10 -> 40. ou_slow: lookback=60 -> 60. W_prim = 60.
    # AST: signal_expression has no ts_* calls -> w_ast = 0.
    # W_max = 60 + 0 + 10 = 70.
    w_max = compute_max_warmup_bars(sample_contract)
    assert w_max == 70

    # With AST lookback: ts_mean(k_fast, 21)
    contract2 = sample_contract.model_copy(update={"signal_expression": "ts_mean(k_fast, 21)"})
    w_max2 = compute_max_warmup_bars(contract2)
    assert w_max2 == 60 + 21 + 10  # 91


def test_canary_test_causal_pass(sample_market_data: MarketData, sample_contract: StrategyContract) -> None:
    strategy = CompiledAlphaStrategy(sample_contract)
    result = run_canary_test(strategy, sample_market_data, seed=42)
    assert result is True


def test_canary_test_catches_lookahead(sample_market_data: MarketData, sample_contract: StrategyContract) -> None:
    strategy = CompiledAlphaStrategy(sample_contract)

    # Intentionally leak future data into precompute_panel
    original_precompute = strategy.precompute_panel

    def leaky_precompute(data: MarketData) -> pd.DataFrame:
        w = original_precompute(data)
        # Shift future values backward to introduce lookahead leak
        return w.shift(-2).fillna(0.0)

    strategy.precompute_panel = leaky_precompute  # type: ignore[method-assign]

    with pytest.raises(LookAheadError, match="Lookahead leak detected"):
        run_canary_test(strategy, sample_market_data, seed=42)


def test_canary_test_catches_inactive_strategy(sample_market_data: MarketData, sample_contract: StrategyContract) -> None:
    contract_inactive = sample_contract.model_copy(
        update={"signal_expression": "0.0 * cs_rank(k_fast)"}
    )
    strategy = CompiledAlphaStrategy(contract_inactive)
    with pytest.raises(ValueError, match="Strategy inactive in Zone 2"):
        run_canary_test(strategy, sample_market_data, seed=42)
