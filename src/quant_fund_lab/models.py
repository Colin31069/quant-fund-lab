from __future__ import annotations

import numpy as np
import pandas as pd

from .config import StrategyConfig

_EPS = 1e-12


def _kalman_path(log_prices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = np.array([[1.0, 1.0], [0.0, 1.0]])
    h = np.array([1.0, 0.0])
    q = np.diag([1e-5, 1e-6])
    r = 5e-4
    x = np.array([float(log_prices[0]), 0.0])
    p = np.eye(2) * 0.1
    levels = np.empty(len(log_prices))
    trends = np.empty(len(log_prices))

    for i, y in enumerate(log_prices):
        x_pred = a @ x
        p_pred = a @ p @ a.T + q
        innovation = float(y - h @ x_pred)
        s = float(h @ p_pred @ h.T + r)
        k = (p_pred @ h) / max(s, _EPS)
        x = x_pred + k * innovation
        p = (np.eye(2) - np.outer(k, h)) @ p_pred
        levels[i] = x[0]
        trends[i] = x[1]
    return levels, trends


def kalman_trend_alpha(close: pd.DataFrame) -> pd.Series:
    scores: dict[str, float] = {}
    for symbol in close.columns:
        series = close[symbol].dropna()
        if len(series) < 30:
            scores[symbol] = 0.0
            continue
        logp = np.log(series.to_numpy(dtype=float))
        _, trends = _kalman_path(logp)
        ret_vol = np.std(np.diff(logp[-60:]), ddof=1) if len(logp) >= 3 else 0.0
        scores[symbol] = float(np.clip(trends[-1] / max(ret_vol, 1e-4), -4.0, 4.0))
    return pd.Series(scores, dtype=float)


def ou_reversion_alpha(close: pd.DataFrame, lookback: int = 60) -> pd.Series:
    scores: dict[str, float] = {}
    for symbol in close.columns:
        series = close[symbol].dropna()
        if len(series) < max(35, lookback // 2):
            scores[symbol] = 0.0
            continue
        logp = np.log(series.to_numpy(dtype=float))
        levels, _ = _kalman_path(logp)
        residual = logp - levels
        x = residual[-lookback:]
        x0, x1 = x[:-1], x[1:]
        design = np.column_stack([np.ones_like(x0), x0])
        intercept, phi = np.linalg.lstsq(design, x1, rcond=None)[0]
        if not (0.0 < phi < 0.995):
            scores[symbol] = 0.0
            continue
        kappa = -np.log(phi)
        long_run_mean = intercept / (1.0 - phi)
        sigma = np.std(x1 - (intercept + phi * x0), ddof=1)
        z = (x[-1] - long_run_mean) / max(sigma, 1e-5)
        scores[symbol] = float(np.clip(-z * min(kappa / 0.05, 2.0), -4.0, 4.0))
    return pd.Series(scores, dtype=float)


def residual_momentum_alpha(close: pd.DataFrame, lookback: int = 60) -> pd.Series:
    returns = close.pct_change(fill_method=None).dropna(how="all").tail(lookback)
    if len(returns) < 20:
        return pd.Series(0.0, index=close.columns, dtype=float)

    market = returns.mean(axis=1, skipna=True)
    market_var = float(market.var(ddof=1))
    raw: dict[str, float] = {}
    for symbol in close.columns:
        r = returns[symbol].dropna()
        aligned_market = market.reindex(r.index)
        if len(r) < 20 or market_var <= _EPS:
            raw[symbol] = 0.0
            continue
        beta = float(np.cov(r, aligned_market, ddof=1)[0, 1] / market_var)
        residual = r - beta * aligned_market
        sigma = float(residual.std(ddof=1))
        raw[symbol] = float(residual.mean() * np.sqrt(len(residual)) / max(sigma, 1e-5))

    series = pd.Series(raw, dtype=float).replace([np.inf, -np.inf], 0.0).fillna(0.0)
    if len(series) > 1 and float(series.std(ddof=0)) > _EPS:
        series = (series - series.mean()) / series.std(ddof=0)
    return series.clip(-4.0, 4.0)


def ensemble_alpha(close: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    kalman = kalman_trend_alpha(close)
    ou = ou_reversion_alpha(close, config.ou_lookback)
    residual = residual_momentum_alpha(close, config.residual_momentum_lookback)
    frame = pd.DataFrame({"kalman": kalman, "ou": ou, "residual_momentum": residual})
    frame["ensemble"] = (
        config.kalman_weight * frame["kalman"]
        + config.ou_weight * frame["ou"]
        + config.residual_momentum_weight * frame["residual_momentum"]
    )
    return frame.replace([np.inf, -np.inf], 0.0).fillna(0.0)
