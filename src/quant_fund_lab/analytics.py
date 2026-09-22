from __future__ import annotations

import math

import pandas as pd


def performance_metrics(equity: pd.Series, periods_per_year: int = 252) -> dict[str, float]:
    equity = equity.dropna().astype(float)
    if len(equity) < 2:
        raise ValueError("at least two equity observations are required")
    returns = equity.pct_change().dropna()
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    years = len(returns) / periods_per_year
    annual_return = float((1.0 + total_return) ** (1.0 / years) - 1.0) if years > 0 else 0.0
    annual_volatility = float(returns.std(ddof=1) * math.sqrt(periods_per_year))
    sharpe = float(returns.mean() / returns.std(ddof=1) * math.sqrt(periods_per_year)) if returns.std(ddof=1) > 0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min())
    calmar = annual_return / abs(max_drawdown) if max_drawdown < 0 else 0.0
    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "calmar": float(calmar),
    }


def buy_and_hold_equity(close: pd.Series, initial_cash: float) -> pd.Series:
    series = close.dropna().astype(float)
    if series.empty:
        raise ValueError("benchmark series is empty")
    return initial_cash * series / float(series.iloc[0])


def metric_frame(named_equity: dict[str, pd.Series]) -> pd.DataFrame:
    rows = {name: performance_metrics(equity) for name, equity in named_equity.items()}
    return pd.DataFrame(rows).T
