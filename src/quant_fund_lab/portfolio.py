from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .config import StrategyConfig
from .research import normalized_risk_contributions


def shrink_covariance(returns: pd.DataFrame, shrinkage: float) -> pd.DataFrame:
    clean = returns.dropna(how="all").fillna(0.0)
    sample = clean.cov()
    diag = pd.DataFrame(np.diag(np.diag(sample)), index=sample.index, columns=sample.columns)
    covariance = (1.0 - shrinkage) * sample + shrinkage * diag
    covariance += np.eye(len(covariance)) * 1e-8
    return covariance


def _fallback_weights(
    alpha: pd.Series,
    max_weight: float,
    eligible: pd.Series | None = None,
    gross_exposure_limit: float = 1.0,
) -> pd.Series:
    positive = alpha.clip(lower=0.0)
    allowed = (
        eligible.reindex(alpha.index).fillna(False).astype(bool)
        if eligible is not None
        else pd.Series(True, index=alpha.index, dtype=bool)
    )
    positive = positive.where(allowed, 0.0)
    if float(positive.sum()) <= 0.0:
        return pd.Series(0.0, index=alpha.index)
    weights = positive / positive.sum()
    for _ in range(10):
        over = weights > max_weight
        if not bool(over.any()):
            break
        excess = float((weights[over] - max_weight).sum())
        weights[over] = max_weight
        under = (~over) & allowed
        capacity = (max_weight - weights[under]).clip(lower=0.0)
        if float(capacity.sum()) <= 0.0:
            break
        weights.loc[under] += excess * capacity / capacity.sum()
    total = float(weights.sum())
    if total > gross_exposure_limit and total > 0.0:
        weights *= gross_exposure_limit / total
    return weights


def optimize_weights(
    alpha: pd.Series,
    returns: pd.DataFrame,
    previous_weights: pd.Series | None,
    config: StrategyConfig,
    eligible: pd.Series | None = None,
    gross_exposure_limit: float = 1.0,
) -> pd.Series:
    symbols = list(alpha.index)
    if not symbols:
        return pd.Series(dtype=float)
    if not (0.0 <= gross_exposure_limit <= 1.0):
        raise ValueError("gross_exposure_limit must be between 0 and 1")
    alpha = alpha.reindex(symbols).fillna(0.0)
    allowed = (
        eligible.reindex(symbols).fillna(False).astype(bool)
        if eligible is not None
        else pd.Series(True, index=symbols, dtype=bool)
    )
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
        risk_budget_penalty = 0.0
        active = allowed.to_numpy(dtype=bool)
        if config.risk_budget_penalty > 0.0 and bool(active.any()):
            normalized_rc = normalized_risk_contributions(w, sigma)
            target = np.zeros(len(symbols), dtype=float)
            target[active] = 1.0 / float(active.sum())
            risk_budget_penalty = config.risk_budget_penalty * float(
                np.sum((normalized_rc - target) ** 2)
            )
        utility = (
            expected_return
            - config.risk_aversion * risk
            - config.turnover_penalty * turnover
            - risk_budget_penalty
        )
        return -utility

    x0 = _fallback_weights(
        alpha, config.max_weight, allowed, gross_exposure_limit
    ).to_numpy(dtype=float)
    result = minimize(
        objective,
        x0=x0,
        method="SLSQP",
        bounds=[(0.0, config.max_weight if bool(allowed[s]) else 0.0) for s in symbols],
        constraints=[
            {"type": "ineq", "fun": lambda w: gross_exposure_limit - float(np.sum(w))}
        ],
        options={"maxiter": 300, "ftol": 1e-10},
    )
    if not result.success or not np.all(np.isfinite(result.x)):
        return _fallback_weights(alpha, config.max_weight, allowed, gross_exposure_limit)
    weights = pd.Series(result.x, index=symbols).clip(lower=0.0, upper=config.max_weight)
    if float(weights.sum()) > gross_exposure_limit + 1e-6:
        weights *= gross_exposure_limit / weights.sum()
    return weights
