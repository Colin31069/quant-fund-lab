import numpy as np
import pandas as pd
import pytest

from quant_fund_lab.backtest import run_backtest
from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.portfolio import optimize_weights, shrink_covariance
from quant_fund_lab.research import (
    detect_market_regime,
    estimate_statistical_factor_exposures,
    neutralize_alpha,
    normalized_risk_contributions,
)


def test_regime_detection_uses_trailing_data_and_caps_exposure():
    dates = pd.bdate_range("2025-01-02", periods=100)
    rising = pd.DataFrame(
        {"AAA": 100.0 * np.exp(np.arange(100) * 0.002), "BBB": 90.0 * np.exp(np.arange(100) * 0.0018)},
        index=dates,
    )
    regime = detect_market_regime(rising, lookback=60)
    assert regime.label == "trend"
    assert regime.gross_exposure_limit == pytest.approx(1.0)

    falling = rising.copy()
    falling.iloc[-60:] = falling.iloc[-60:].iloc[0].to_numpy() * np.exp(
        -np.arange(60)[:, None] * 0.003
    )
    stressed = detect_market_regime(falling, lookback=60)
    assert stressed.label in {"risk_off", "stress"}
    assert stressed.gross_exposure_limit <= 0.55


def test_factor_neutralization_removes_cross_sectional_beta_loading():
    rng = np.random.default_rng(4)
    dates = pd.bdate_range("2025-01-02", periods=100)
    market = rng.normal(0.0002, 0.01, size=len(dates))
    betas = np.array([0.5, 0.8, 1.2, 1.6, 2.0])
    returns = pd.DataFrame(
        {
            f"S{i}": beta * market + rng.normal(0.0, 0.004 + i * 0.0005, size=len(dates))
            for i, beta in enumerate(betas)
        },
        index=dates,
    )
    exposures = estimate_statistical_factor_exposures(returns)
    alpha = exposures["market_beta"] * 2.0 + pd.Series(
        [0.2, -0.1, 0.15, -0.05, 0.1], index=returns.columns
    )
    neutral, estimated = neutralize_alpha(alpha, returns)
    correlation = np.corrcoef(neutral, estimated["market_beta"])[0, 1]
    assert abs(float(correlation)) < 1e-10
    assert np.isfinite(neutral.to_numpy()).all()


def test_risk_budgeting_reduces_concentration_of_risk_contributions():
    data = synthetic_market_data(symbols=("AAA", "BBB", "CCC", "DDD"), periods=260, seed=19)
    returns = data.close.pct_change(fill_method=None).tail(100)
    alpha = pd.Series(1.0, index=returns.columns)
    base = StrategyConfig(max_weight=0.8, risk_aversion=0.5, turnover_penalty=0.0, risk_budget_penalty=0.0)
    budgeted = StrategyConfig(
        max_weight=0.8,
        risk_aversion=0.5,
        turnover_penalty=0.0,
        risk_budget_penalty=0.01,
    )
    w_plain = optimize_weights(alpha, returns, None, base)
    w_budget = optimize_weights(alpha, returns, None, budgeted)
    sigma = shrink_covariance(returns, base.covariance_shrinkage).to_numpy(dtype=float)
    plain_rc = normalized_risk_contributions(w_plain.to_numpy(dtype=float), sigma)
    budget_rc = normalized_risk_contributions(w_budget.to_numpy(dtype=float), sigma)
    target = np.full(len(alpha), 1.0 / len(alpha))
    assert np.sum((budget_rc - target) ** 2) <= np.sum((plain_rc - target) ** 2) + 1e-10


def test_partial_neutralization_preserves_some_raw_alpha():
    data = synthetic_market_data(symbols=("AAA", "BBB", "CCC", "DDD"), periods=240, seed=31)
    raw = pd.Series({"AAA": 1.0, "BBB": 0.5, "CCC": -0.2, "DDD": 0.8})
    returns = data.close.pct_change(fill_method=None).tail(60)
    neutral, _ = neutralize_alpha(raw, returns)
    strength = 0.5
    blended = (1.0 - strength) * raw + strength * neutral
    assert not np.allclose(blended.to_numpy(), neutral.to_numpy())
    assert not np.allclose(blended.to_numpy(), raw.to_numpy())


def test_backtest_records_regime_and_obeys_gross_exposure_limit():
    data = synthetic_market_data(symbols=("AAA", "BBB", "CCC", "DDD"), periods=280, seed=8)
    config = BacktestConfig(
        strategy=StrategyConfig(warmup_days=100, rebalance_every=5, max_weight=0.6)
    )
    result = run_backtest(data, config)
    assert not result.regimes.empty
    aligned_limits = result.regimes["gross_exposure_limit"].reindex(result.weights.index)
    gross = result.weights.sum(axis=1)
    assert (gross <= aligned_limits + 1e-6).all()
