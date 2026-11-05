"""Performance drift monitoring and automated retirement triggers for live paper trading."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DriftReport:
    """Diagnostic health assessment of a deployed strategy in forward paper trading."""

    strategy_name: str
    as_of_date: str
    rolling_sharpe_60d: float
    bootstrap_p01: float
    bootstrap_p05: float
    status: Literal["HEALTHY", "WARNING", "RETIRE"]
    message: str


def compute_rolling_sharpe(
    returns: pd.Series | np.ndarray,
    window: int = 60,
    annualization_factor: float = 252.0,
) -> float:
    """Compute annualized Sharpe ratio over trailing window trading bars."""
    if isinstance(returns, pd.Series):
        r = returns.dropna().tail(window).to_numpy(dtype=np.float64)
    else:
        r = np.asarray(returns, dtype=np.float64)[-window:]

    if len(r) < max(10, window // 4):
        return 0.0

    std = float(np.std(r, ddof=1))
    if std <= 1e-12:
        return 0.0
    mean = float(np.mean(r))
    return float(math.sqrt(annualization_factor) * (mean / std))


def check_strategy_drift(
    strategy_name: str,
    live_returns: pd.Series | np.ndarray,
    bootstrap_p01: float,
    bootstrap_p05: float,
    window: int = 60,
    as_of_date: str = "",
) -> DriftReport:
    """Compare rolling paper-trading performance against Block Bootstrap distributions.

    Triggers:
    - RETIRE: Rolling Sharpe breaches empirical 1st percentile (unprecedented breakdown).
    - WARNING: Rolling Sharpe falls below 5th percentile (statistically anomalous underperformance).
    - HEALTHY: Normal operation within bootstrap confidence bounds.
    """
    rolling_sharpe = compute_rolling_sharpe(live_returns, window=window)

    if rolling_sharpe < bootstrap_p01:
        status: Literal["HEALTHY", "WARNING", "RETIRE"] = "RETIRE"
        message = (
            f"CRITICAL: 60-day rolling Sharpe ({rolling_sharpe:.2f}) breached the 1st percentile "
            f"bootstrap threshold ({bootstrap_p01:.2f}). Triggering immediate strategy retirement."
        )
    elif rolling_sharpe < bootstrap_p05:
        status = "WARNING"
        message = (
            f"WARNING: 60-day rolling Sharpe ({rolling_sharpe:.2f}) fell below the 5th percentile "
            f"bootstrap threshold ({bootstrap_p05:.2f}). Monitoring for structural decay."
        )
    else:
        status = "HEALTHY"
        message = (
            f"HEALTHY: 60-day rolling Sharpe ({rolling_sharpe:.2f}) operates comfortably above "
            f"bootstrap thresholds (p05: {bootstrap_p05:.2f}, p01: {bootstrap_p01:.2f})."
        )

    return DriftReport(
        strategy_name=strategy_name,
        as_of_date=as_of_date,
        rolling_sharpe_60d=round(rolling_sharpe, 3),
        bootstrap_p01=round(bootstrap_p01, 3),
        bootstrap_p05=round(bootstrap_p05, 3),
        status=status,
        message=message,
    )


def audit_ensemble_drift(
    ensemble_returns: dict[str, pd.Series | np.ndarray],
    bootstrap_thresholds: dict[str, tuple[float, float]],
    window: int = 60,
    as_of_date: str = "",
) -> list[DriftReport]:
    """Audit drift across all sleeves in the active ensemble."""
    reports: list[DriftReport] = []
    for name, returns in ensemble_returns.items():
        if name in bootstrap_thresholds:
            p01, p05 = bootstrap_thresholds[name]
            reports.append(
                check_strategy_drift(
                    strategy_name=name,
                    live_returns=returns,
                    bootstrap_p01=p01,
                    bootstrap_p05=p05,
                    window=window,
                    as_of_date=as_of_date,
                )
            )
    return reports
