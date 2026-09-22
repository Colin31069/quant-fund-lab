from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import StrategyConfig

_EPS = 1e-12


@dataclass(frozen=True)
class MarketRegime:
    label: str
    trend_z: float
    annual_volatility: float
    gross_exposure_limit: float
    kalman_scale: float
    ou_scale: float
    residual_momentum_scale: float


def detect_market_regime(
    close: pd.DataFrame,
    lookback: int = 60,
) -> MarketRegime:
    """Classify the current market state using only trailing equal-weight returns."""

    returns = close.pct_change(fill_method=None).dropna(how="all").tail(lookback)
    market = returns.mean(axis=1, skipna=True).dropna()
    if len(market) < 20:
        return MarketRegime("insufficient_history", 0.0, 0.0, 0.75, 1.0, 1.0, 1.0)

    mean = float(market.mean())
    vol = float(market.std(ddof=1))
    trend_z = mean / max(vol, _EPS) * np.sqrt(len(market))
    annual_volatility = vol * np.sqrt(252.0)

    if annual_volatility >= 0.30 and trend_z <= -0.50:
        return MarketRegime("stress", trend_z, annual_volatility, 0.35, 0.55, 1.45, 0.55)
    if trend_z <= -0.75:
        return MarketRegime("risk_off", trend_z, annual_volatility, 0.55, 0.70, 1.30, 0.70)
    if annual_volatility >= 0.30:
        return MarketRegime("high_volatility", trend_z, annual_volatility, 0.60, 0.80, 1.20, 0.80)
    if trend_z >= 0.75:
        return MarketRegime("trend", trend_z, annual_volatility, 1.00, 1.30, 0.60, 1.15)
    return MarketRegime("neutral", trend_z, annual_volatility, 0.85, 1.00, 1.00, 1.00)


def regime_adjusted_alpha(
    component_alpha: pd.DataFrame,
    config: StrategyConfig,
    regime: MarketRegime,
) -> pd.Series:
    """Blend model components after applying regime-dependent model weights."""

    weighted = (
        config.kalman_weight * regime.kalman_scale * component_alpha["kalman"]
        + config.ou_weight * regime.ou_scale * component_alpha["ou"]
        + config.residual_momentum_weight
        * regime.residual_momentum_scale
        * component_alpha["residual_momentum"]
    )
    denominator = (
        config.kalman_weight * regime.kalman_scale
        + config.ou_weight * regime.ou_scale
        + config.residual_momentum_weight * regime.residual_momentum_scale
    )
    return (weighted / max(denominator, _EPS)).replace([np.inf, -np.inf], 0.0).fillna(0.0)


def estimate_statistical_factor_exposures(
    returns: pd.DataFrame,
) -> pd.DataFrame:
    """Estimate market-beta and idiosyncratic-volatility exposures from trailing returns."""

    clean = returns.dropna(how="all")
    symbols = list(returns.columns)
    market = clean.mean(axis=1, skipna=True)
    market_var = float(market.var(ddof=1)) if len(market) > 1 else 0.0
    rows: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        r = clean[symbol].dropna()
        aligned_market = market.reindex(r.index).dropna()
        r = r.reindex(aligned_market.index)
        if len(r) < 20 or market_var <= _EPS:
            rows[symbol] = {"market_beta": 0.0, "idiosyncratic_volatility": 0.0}
            continue
        beta = float(np.cov(r, aligned_market, ddof=1)[0, 1] / market_var)
        residual = r - beta * aligned_market
        rows[symbol] = {
            "market_beta": beta,
            "idiosyncratic_volatility": float(residual.std(ddof=1) * np.sqrt(252.0)),
        }
    return pd.DataFrame.from_dict(rows, orient="index").reindex(symbols).fillna(0.0)


def neutralize_alpha(
    alpha: pd.Series,
    returns: pd.DataFrame,
    eligible: pd.Series | None = None,
) -> tuple[pd.Series, pd.DataFrame]:
    """Cross-sectionally residualize alpha against statistical risk factors.

    The regression is fit only on currently eligible names. With fewer than three eligible
    names there is not enough cross-sectional information, so alpha is returned unchanged.
    """

    symbols = list(alpha.index)
    allowed = (
        eligible.reindex(symbols).fillna(False).astype(bool)
        if eligible is not None
        else pd.Series(True, index=symbols, dtype=bool)
    )
    exposures = estimate_statistical_factor_exposures(returns.reindex(columns=symbols))
    active = [symbol for symbol in symbols if bool(allowed[symbol])]
    result = alpha.reindex(symbols).fillna(0.0).copy()
    if len(active) < 3:
        result.loc[~allowed] = 0.0
        return result, exposures

    candidate_factors = ["market_beta"]
    if len(active) >= 4:
        candidate_factors.append("idiosyncratic_volatility")

    x = exposures.loc[active, candidate_factors].astype(float).copy()
    for column in candidate_factors:
        std = float(x[column].std(ddof=0))
        x[column] = (x[column] - x[column].mean()) / max(std, _EPS)
    design = np.column_stack([np.ones(len(active)), x.to_numpy(dtype=float)])
    y = result.loc[active].to_numpy(dtype=float)
    coefficients = np.linalg.lstsq(design, y, rcond=None)[0]
    residual = y - design @ coefficients
    result.loc[active] = residual
    result.loc[~allowed] = 0.0
    return result.replace([np.inf, -np.inf], 0.0).fillna(0.0), exposures


def normalized_risk_contributions(weights: np.ndarray, covariance: np.ndarray) -> np.ndarray:
    """Return each asset's fraction of portfolio variance; zeros for a zero-risk portfolio."""

    marginal = covariance @ weights
    contributions = weights * marginal
    total = float(contributions.sum())
    if total <= _EPS:
        return np.zeros_like(weights)
    return contributions / total
