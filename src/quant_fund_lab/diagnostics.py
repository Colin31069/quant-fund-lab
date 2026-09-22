from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew

from .walkforward import WalkForwardResult

_EULER_MASCHERONI = 0.5772156649015329


@dataclass(frozen=True)
class DeflatedSharpeResult:
    probability: float
    z_stat: float
    observed_sharpe_daily: float
    observed_sharpe_annualized: float
    expected_max_sharpe_daily: float
    expected_max_sharpe_annualized: float
    trial_sharpe_std_daily: float
    num_trials: int
    sample_size: int
    skewness: float
    kurtosis: float


@dataclass(frozen=True)
class RealityCheckResult:
    p_value: float
    observed_best_mean_return: float
    best_candidate_id: str
    candidate_count: int
    sample_size: int
    bootstrap_iterations: int
    mean_block_length: float
    monte_carlo_se: float


@dataclass(frozen=True)
class MultipleTestingDiagnostics:
    deflated_sharpe: DeflatedSharpeResult
    reality_check: RealityCheckResult


def _daily_sharpe(returns: pd.Series) -> float:
    values = returns.dropna().astype(float)
    if len(values) < 2:
        return 0.0
    std = float(values.std(ddof=1))
    if std <= 0.0 or not np.isfinite(std):
        return 0.0
    return float(values.mean() / std)


def expected_max_sharpe(num_trials: int, trial_sharpe_std: float) -> float:
    """Expected best daily Sharpe under a zero-skill multiple-testing null."""

    if num_trials <= 1 or trial_sharpe_std <= 0.0:
        return 0.0
    n = float(num_trials)
    extreme = (
        (1.0 - _EULER_MASCHERONI) * norm.ppf(1.0 - 1.0 / n)
        + _EULER_MASCHERONI * norm.ppf(1.0 - 1.0 / (n * np.e))
    )
    return float(trial_sharpe_std * extreme)


def deflated_sharpe_ratio(
    returns: pd.Series,
    trial_sharpes_daily: pd.Series | np.ndarray,
    periods_per_year: int = 252,
) -> DeflatedSharpeResult:
    """Bailey/Lopez de Prado-style DSR using per-period Sharpe quantities.

    The selection threshold assumes the zero-skill null and uses the cross-sectional
    standard deviation of Sharpe ratios observed across strategy trials.
    """

    clean = returns.dropna().astype(float)
    if len(clean) < 3:
        raise ValueError("DSR requires at least three return observations")
    std = float(clean.std(ddof=1))
    if std <= 0.0 or not np.isfinite(std):
        raise ValueError("DSR requires non-zero finite return volatility")

    trials = np.asarray(trial_sharpes_daily, dtype=float)
    trials = trials[np.isfinite(trials)]
    if len(trials) == 0:
        raise ValueError("DSR requires at least one finite trial Sharpe ratio")
    trial_std = float(np.std(trials, ddof=1)) if len(trials) > 1 else 0.0
    threshold = expected_max_sharpe(len(trials), trial_std)

    observed = float(clean.mean() / std)
    sample_skew = float(skew(clean.to_numpy(), bias=False))
    sample_kurtosis = float(kurtosis(clean.to_numpy(), fisher=False, bias=False))
    if not np.isfinite(sample_skew):
        sample_skew = 0.0
    if not np.isfinite(sample_kurtosis):
        sample_kurtosis = 3.0
    denominator_sq = (
        1.0
        - sample_skew * observed
        + ((sample_kurtosis - 1.0) / 4.0) * observed * observed
    )
    if denominator_sq <= 0.0 or not np.isfinite(denominator_sq):
        raise ValueError("DSR sampling-variance denominator is not positive")
    z_stat = float(
        (observed - threshold)
        * np.sqrt(len(clean) - 1.0)
        / np.sqrt(denominator_sq)
    )
    probability = float(norm.cdf(z_stat))
    annualizer = float(np.sqrt(periods_per_year))
    return DeflatedSharpeResult(
        probability=probability,
        z_stat=z_stat,
        observed_sharpe_daily=observed,
        observed_sharpe_annualized=observed * annualizer,
        expected_max_sharpe_daily=threshold,
        expected_max_sharpe_annualized=threshold * annualizer,
        trial_sharpe_std_daily=trial_std,
        num_trials=len(trials),
        sample_size=len(clean),
        skewness=sample_skew,
        kurtosis=sample_kurtosis,
    )


def _stationary_bootstrap_indices(
    sample_size: int,
    mean_block_length: float,
    rng: np.random.Generator,
) -> np.ndarray:
    if sample_size < 2:
        raise ValueError("bootstrap requires at least two observations")
    if mean_block_length < 1.0:
        raise ValueError("mean_block_length must be >= 1")
    restart_probability = min(1.0, 1.0 / mean_block_length)
    indices = np.empty(sample_size, dtype=int)
    indices[0] = int(rng.integers(sample_size))
    for i in range(1, sample_size):
        if rng.random() < restart_probability:
            indices[i] = int(rng.integers(sample_size))
        else:
            indices[i] = (indices[i - 1] + 1) % sample_size
    return indices


def reality_check_bootstrap(
    candidate_returns: pd.DataFrame,
    benchmark_returns: pd.Series | None = None,
    bootstrap_iterations: int = 1000,
    mean_block_length: float = 10.0,
    seed: int = 11,
) -> RealityCheckResult:
    """White Reality Check-style max-mean stationary bootstrap diagnostic.

    All candidate columns use identical bootstrap indices, preserving their contemporaneous
    cross-sectional dependence. Candidate return differentials are centered under the null.
    """

    if bootstrap_iterations < 100:
        raise ValueError("bootstrap_iterations must be at least 100")
    returns = candidate_returns.astype(float).copy()
    if benchmark_returns is not None:
        benchmark = benchmark_returns.reindex(returns.index)
        returns = returns.sub(benchmark, axis=0)
    returns = returns.dropna(how="any")
    if len(returns) < 10 or returns.shape[1] < 1:
        raise ValueError("Reality Check requires >=10 complete rows and >=1 candidate")
    if not np.isfinite(returns.to_numpy()).all():
        raise ValueError("candidate returns must be finite")

    means = returns.mean(axis=0)
    best_candidate = str(means.idxmax())
    observed = float(means.max())
    centered = returns - means
    centered_values = centered.to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    maxima = np.empty(bootstrap_iterations, dtype=float)
    for draw in range(bootstrap_iterations):
        indices = _stationary_bootstrap_indices(
            len(centered_values), mean_block_length, rng
        )
        maxima[draw] = float(centered_values[indices].mean(axis=0).max())

    exceedances = int(np.count_nonzero(maxima >= observed))
    p_value = float((exceedances + 1.0) / (bootstrap_iterations + 1.0))
    mc_se = float(np.sqrt(p_value * (1.0 - p_value) / bootstrap_iterations))
    return RealityCheckResult(
        p_value=p_value,
        observed_best_mean_return=observed,
        best_candidate_id=best_candidate,
        candidate_count=returns.shape[1],
        sample_size=len(returns),
        bootstrap_iterations=bootstrap_iterations,
        mean_block_length=float(mean_block_length),
        monte_carlo_se=mc_se,
    )


def diagnose_walk_forward(
    result: WalkForwardResult,
    bootstrap_iterations: int = 1000,
    mean_block_length: float = 10.0,
    seed: int = 11,
) -> MultipleTestingDiagnostics:
    validation_returns = result.candidate_validation_returns
    if validation_returns.empty:
        raise ValueError("walk-forward result has no candidate validation returns")
    trial_sharpes = validation_returns.apply(_daily_sharpe, axis=0)
    oos_returns = result.oos_equity.pct_change().dropna()
    dsr = deflated_sharpe_ratio(oos_returns, trial_sharpes)
    reality_check = reality_check_bootstrap(
        validation_returns,
        bootstrap_iterations=bootstrap_iterations,
        mean_block_length=mean_block_length,
        seed=seed,
    )
    return MultipleTestingDiagnostics(deflated_sharpe=dsr, reality_check=reality_check)
