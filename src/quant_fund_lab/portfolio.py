from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .config import StrategyConfig


def shrink_covariance(returns: pd.DataFrame, shrinkage: float) -> pd.DataFrame:
    clean = returns.dropna(how="all").fillna(0.0)
    sample = clean.cov()
    diag = pd.DataFrame(np.diag(np.diag(sample)), index=sample.index, columns=sample.columns)
    covariance = (1.0 - shrinkage) * sample + shrinkage * diag
    covariance += np.eye(len(covariance)) * 1e-8
    return covariance


def _fallback_weights(alpha: pd.Series, max_weight: float) -> pd.Series:
    positive = alpha.clip(lower=0.0)
    if float(positive.sum()) <= 0.0:
        return pd.Series(0.0, index=alpha.index)
    weights = positive / positive.sum()
    for _ in range(10):
        over = weights > max_weight
        if not bool(over.any()):
            break
        excess = float((weights[over] - max_weight).sum())
        weights[over] = max_weight
        under = ~over
        capacity = (max_weight - weights[under]).clip(lower=0.0)
        if float(capacity.sum()) <= 0.0:
            break
        weights.loc[under] += excess * capacity / capacity.sum()
    total = float(weights.sum())
    if total > 1.0:
        weights /= total
    return weights


def optimize_weights(
    alpha: pd.Series,
    returns: pd.DataFrame,
    previous_weights: pd.Series | None,
    config: StrategyConfig,
) -> pd.Series:
    symbols = list(alpha.index)
    if not symbols:
        return pd.Series(dtype=float)
    alpha = alpha.reindex(symbols).fillna(0.0)
    prev = (
        previous_weights.reindex(symbols).fillna(0.0)
        if previous_weights is not None
        else pd.Series(0.0, index=symbols)
    )
    cov = shrink_covariance(returns.reindex(columns=symbols), config.covariance_shrinkage)
    expected = alpha.to_numpy(dtype=float) * config.alpha_daily_scale
    sigma = cov.to_numpy(dtype=float)
    prev_np = prev.to_numpy(dtype=float)

    def objective(w: np.ndarray) -> float:
        expected_return = float(expected @ w)
        risk = float(w @ sigma @ w)
        turnover = float(np.sum((w - prev_np) ** 2))
        utility = expected_return - config.risk_aversion * risk - config.turnover_penalty * turnover
        return -utility

    x0 = _fallback_weights(alpha, config.max_weight).to_numpy(dtype=float)
    result = minimize(
        objective,
        x0=x0,
        method="SLSQP",
        bounds=[(0.0, config.max_weight)] * len(symbols),
        constraints=[{"type": "ineq", "fun": lambda w: 1.0 - float(np.sum(w))}],
        options={"maxiter": 300, "ftol": 1e-10},
    )
    if not result.success or not np.all(np.isfinite(result.x)):
        return _fallback_weights(alpha, config.max_weight)
    weights = pd.Series(result.x, index=symbols).clip(lower=0.0, upper=config.max_weight)
    if float(weights.sum()) > 1.000001:
        weights /= weights.sum()
    return weights
