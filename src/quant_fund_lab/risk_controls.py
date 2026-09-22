from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import numpy as np
import pandas as pd

from .portfolio import shrink_covariance

_EPS = 1e-12


@dataclass(frozen=True)
class RiskControlResult:
    weights: pd.Series
    forecast_annual_volatility_before: float
    forecast_annual_volatility_after: float
    historical_cvar_before: float
    historical_cvar_after: float
    volatility_scale: float
    cvar_scale: float
    drawdown_scale: float
    final_scale: float


def portfolio_annualized_volatility(
    weights: pd.Series,
    returns: pd.DataFrame,
    covariance_shrinkage: float = 0.35,
) -> float:
    symbols = list(weights.index)
    if not symbols or returns.empty:
        return 0.0
    covariance = shrink_covariance(
        returns.reindex(columns=symbols), covariance_shrinkage
    ).to_numpy(dtype=float)
    vector = weights.reindex(symbols).fillna(0.0).to_numpy(dtype=float)
    variance = max(float(vector @ covariance @ vector), 0.0)
    return float(sqrt(variance * 252.0))


def historical_cvar(
    weights: pd.Series,
    returns: pd.DataFrame,
    confidence: float = 0.95,
) -> float:
    """Positive daily Expected Shortfall estimated from trailing portfolio returns."""

    if not 0.50 < confidence < 1.0:
        raise ValueError("confidence must be between 0.50 and 1.0")
    symbols = list(weights.index)
    clean = returns.reindex(columns=symbols).dropna(how="all").fillna(0.0)
    if clean.empty:
        return 0.0
    vector = weights.reindex(symbols).fillna(0.0).to_numpy(dtype=float)
    portfolio_returns = clean.to_numpy(dtype=float) @ vector
    if len(portfolio_returns) < 5:
        return 0.0
    cutoff = float(np.quantile(portfolio_returns, 1.0 - confidence))
    tail = portfolio_returns[portfolio_returns <= cutoff]
    if len(tail) == 0:
        return 0.0
    return max(float(-tail.mean()), 0.0)


def drawdown_exposure_scale(
    drawdown: float,
    soft_limit: float,
    hard_limit: float,
    min_exposure: float,
) -> float:
    """Linearly de-risk between soft/hard drawdown thresholds."""

    if not 0.0 <= drawdown <= 1.0:
        raise ValueError("drawdown must be between 0 and 1")
    if not 0.0 < soft_limit < hard_limit <= 1.0:
        raise ValueError("drawdown limits must satisfy 0 < soft < hard <= 1")
    if not 0.0 <= min_exposure <= 1.0:
        raise ValueError("min_exposure must be between 0 and 1")
    if drawdown <= soft_limit:
        return 1.0
    if drawdown >= hard_limit:
        return float(min_exposure)
    progress = (drawdown - soft_limit) / (hard_limit - soft_limit)
    return float(1.0 - progress * (1.0 - min_exposure))


def apply_portfolio_risk_controls(
    weights: pd.Series,
    returns: pd.DataFrame,
    covariance_shrinkage: float,
    drawdown: float,
    target_annual_volatility: float | None = None,
    max_daily_cvar: float | None = None,
    cvar_confidence: float = 0.95,
    drawdown_soft_limit: float | None = None,
    drawdown_hard_limit: float | None = None,
    drawdown_min_exposure: float = 0.25,
) -> RiskControlResult:
    """Scale a long-only risky sleeve downward; never lever above optimizer output."""

    forecast_vol = portfolio_annualized_volatility(weights, returns, covariance_shrinkage)
    cvar = historical_cvar(weights, returns, cvar_confidence)

    volatility_scale = 1.0
    if target_annual_volatility is not None:
        if target_annual_volatility <= 0.0:
            raise ValueError("target_annual_volatility must be positive")
        if forecast_vol > target_annual_volatility and forecast_vol > _EPS:
            volatility_scale = target_annual_volatility / forecast_vol

    cvar_scale = 1.0
    if max_daily_cvar is not None:
        if max_daily_cvar <= 0.0:
            raise ValueError("max_daily_cvar must be positive")
        if cvar > max_daily_cvar and cvar > _EPS:
            cvar_scale = max_daily_cvar / cvar

    drawdown_scale = 1.0
    if drawdown_soft_limit is not None or drawdown_hard_limit is not None:
        if drawdown_soft_limit is None or drawdown_hard_limit is None:
            raise ValueError("both drawdown soft and hard limits are required")
        drawdown_scale = drawdown_exposure_scale(
            drawdown,
            drawdown_soft_limit,
            drawdown_hard_limit,
            drawdown_min_exposure,
        )

    final_scale = float(np.clip(min(volatility_scale, cvar_scale, drawdown_scale), 0.0, 1.0))
    scaled = weights.astype(float) * final_scale
    return RiskControlResult(
        weights=scaled,
        forecast_annual_volatility_before=forecast_vol,
        forecast_annual_volatility_after=forecast_vol * final_scale,
        historical_cvar_before=cvar,
        historical_cvar_after=cvar * final_scale,
        volatility_scale=float(volatility_scale),
        cvar_scale=float(cvar_scale),
        drawdown_scale=float(drawdown_scale),
        final_scale=final_scale,
    )
