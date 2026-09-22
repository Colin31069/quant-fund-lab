import numpy as np
import pandas as pd
import pytest

from quant_fund_lab.backtest import run_backtest
from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.risk_controls import (
    apply_portfolio_risk_controls,
    drawdown_exposure_scale,
)


def test_volatility_target_only_scales_down():
    rng = np.random.default_rng(2)
    returns = pd.DataFrame(
        rng.normal(0.0, 0.03, size=(200, 3)), columns=["A", "B", "C"]
    )
    weights = pd.Series({"A": 0.4, "B": 0.3, "C": 0.3})
    result = apply_portfolio_risk_controls(
        weights,
        returns,
        covariance_shrinkage=0.35,
        drawdown=0.0,
        target_annual_volatility=0.10,
    )
    assert 0.0 < result.final_scale <= 1.0
    assert result.forecast_annual_volatility_after <= 0.100001
    assert float(result.weights.sum()) <= float(weights.sum()) + 1e-12


def test_cvar_cap_scales_crash_tail():
    returns = pd.DataFrame(
        {
            "A": [0.002] * 90 + [-0.08] * 10,
            "B": [0.001] * 90 + [-0.04] * 10,
        }
    )
    weights = pd.Series({"A": 0.6, "B": 0.4})
    result = apply_portfolio_risk_controls(
        weights,
        returns,
        covariance_shrinkage=0.35,
        drawdown=0.0,
        max_daily_cvar=0.02,
        cvar_confidence=0.95,
    )
    assert result.cvar_scale < 1.0
    assert result.historical_cvar_after <= 0.020001


def test_drawdown_scale_is_monotonic_and_bounded():
    assert drawdown_exposure_scale(0.05, 0.10, 0.20, 0.25) == pytest.approx(1.0)
    assert drawdown_exposure_scale(0.15, 0.10, 0.20, 0.25) == pytest.approx(0.625)
    assert drawdown_exposure_scale(0.25, 0.10, 0.20, 0.25) == pytest.approx(0.25)


def test_backtest_records_and_applies_risk_controls():
    data = synthetic_market_data(
        symbols=("A", "B", "C", "D", "E", "F"), periods=300, seed=73
    )
    config = BacktestConfig(
        initial_cash=500_000,
        strategy=StrategyConfig(
            warmup_days=100,
            rebalance_every=10,
            max_weight=0.3,
            volatility_target_enabled=True,
            target_annual_volatility=0.05,
            cvar_control_enabled=True,
            max_daily_cvar=0.01,
            drawdown_control_enabled=True,
            drawdown_soft_limit=0.03,
            drawdown_hard_limit=0.10,
            drawdown_min_exposure=0.25,
        ),
    )
    result = run_backtest(data, config)
    controls = result.risk_controls
    assert not controls.empty
    assert (controls["final_scale"] <= 1.000001).all()
    assert (controls["gross_after"] <= controls["gross_before"] + 1e-9).all()
    assert (controls["forecast_annual_volatility_after"] <= 0.050001).all()
    assert (controls["historical_cvar_after"] <= 0.010001).all()
    assert (controls["final_scale"] < 0.999).any()
