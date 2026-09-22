from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import numpy as np
import pandas as pd

from .data import MarketData

_EPS = 1e-12


@dataclass(frozen=True)
class FactorResearchResult:
    factor_panel: pd.DataFrame
    ic_series: pd.DataFrame
    summary: pd.DataFrame
    decay: pd.DataFrame
    factor_correlation: pd.DataFrame
    turnover: pd.Series


@dataclass(frozen=True)
class FactorAlphaSignal:
    score: pd.Series
    weights: pd.Series


def _cross_sectional_zscore(frame: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(np.nan, index=frame.index, columns=frame.columns, dtype=float)
    for timestamp in frame.index:
        mask = eligible.loc[timestamp].reindex(frame.columns).fillna(False).astype(bool)
        row = frame.loc[timestamp].where(mask).replace([np.inf, -np.inf], np.nan)
        active = row.dropna()
        if len(active) < 2:
            continue
        lower = float(active.quantile(0.01))
        upper = float(active.quantile(0.99))
        clipped = active.clip(lower=lower, upper=upper)
        std = float(clipped.std(ddof=0))
        if std <= _EPS:
            result.loc[timestamp, clipped.index] = 0.0
        else:
            result.loc[timestamp, clipped.index] = (clipped - clipped.mean()) / std
    return result


def _rolling_beta(returns: pd.DataFrame, lookback: int) -> pd.DataFrame:
    market = returns.mean(axis=1, skipna=True)
    market_var = market.rolling(lookback, min_periods=max(20, lookback // 2)).var()
    output = pd.DataFrame(index=returns.index, columns=returns.columns, dtype=float)
    for symbol in returns.columns:
        covariance = returns[symbol].rolling(
            lookback, min_periods=max(20, lookback // 2)
        ).cov(market)
        output[symbol] = covariance / market_var.replace(0.0, np.nan)
    return output


def build_market_factor_panel(
    data: MarketData,
    sampling_every: int = 5,
    external_factors: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Build leak-free cross-sectional factor snapshots from data available at each timestamp.

    Positive scores always mean "more preferred". External factors must already be point-in-time
    aligned; the function never forward-fills them because doing so can silently create stale-data
    assumptions that belong in the upstream fundamental-data layer.
    """

    if sampling_every < 1:
        raise ValueError("sampling_every must be >= 1")
    close = data.close.astype(float)
    if data.fx_to_base is not None:
        base_close = close * data.fx_to_base.astype(float)
    else:
        base_close = close
    volume = data.volume.astype(float)
    returns = base_close.pct_change(fill_method=None)
    log_close = np.log(base_close.where(base_close > 0.0))

    raw: dict[str, pd.DataFrame] = {
        "momentum_252_21": log_close.shift(21) - log_close.shift(252),
        "momentum_63_5": log_close.shift(5) - log_close.shift(63),
        "short_reversal_5": -base_close.pct_change(5, fill_method=None),
        "low_volatility_60": -returns.rolling(60, min_periods=30).std() * sqrt(252.0),
        "low_beta_126": -_rolling_beta(returns, 126),
        "liquidity_20": np.log(
            (base_close * volume).rolling(20, min_periods=10).mean().where(lambda x: x > 0.0)
        ),
        "volume_surprise_5_20": np.log(
            volume.rolling(5, min_periods=5).mean()
            / volume.rolling(20, min_periods=10).mean().replace(0.0, np.nan)
        ),
    }
    if external_factors:
        for name, factor in external_factors.items():
            if not factor.index.equals(close.index) or list(factor.columns) != list(close.columns):
                raise ValueError(f"external factor {name!r} must align exactly with market data")
            raw[name] = factor.astype(float)

    sampled_index = close.index[::sampling_every]
    eligible = data.membership.astype(bool)
    frames: list[pd.DataFrame] = []
    for factor_name, values in raw.items():
        standardized = _cross_sectional_zscore(values, eligible).loc[sampled_index]
        stacked = standardized.stack(future_stack=True).dropna().rename("score").to_frame()
        stacked["factor"] = factor_name
        frames.append(stacked.reset_index().rename(columns={"level_0": "timestamp", "level_1": "symbol"}))
    if not frames:
        return pd.DataFrame(columns=["timestamp", "symbol", "factor", "score"])
    panel = pd.concat(frames, ignore_index=True)
    panel["timestamp"] = pd.to_datetime(panel["timestamp"])
    return panel.set_index(["timestamp", "symbol", "factor"]).sort_index()


def _forward_returns(close: pd.DataFrame, horizon: int) -> pd.DataFrame:
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    return close.shift(-horizon) / close - 1.0


def information_coefficient_series(
    factor_panel: pd.DataFrame,
    close: pd.DataFrame,
    horizons: tuple[int, ...] = (1, 5, 20),
    min_cross_section: int = 3,
) -> pd.DataFrame:
    """Compute Pearson IC and Spearman Rank IC for each factor/date/horizon."""

    if min_cross_section < 3:
        raise ValueError("min_cross_section must be >= 3")
    if factor_panel.empty:
        return pd.DataFrame(
            columns=["realized_at", "factor", "horizon", "ic", "rank_ic", "n"]
        )
    rows: list[dict[str, object]] = []
    for horizon in horizons:
        forward = _forward_returns(close, horizon)
        for timestamp in factor_panel.index.get_level_values("timestamp").unique():
            if timestamp not in forward.index:
                continue
            by_factor = factor_panel.xs(timestamp, level="timestamp")
            for factor in by_factor.index.get_level_values("factor").unique():
                scores = by_factor.xs(factor, level="factor")["score"]
                future = forward.loc[timestamp].reindex(scores.index)
                aligned = pd.concat([scores.rename("score"), future.rename("forward")], axis=1).dropna()
                if len(aligned) < min_cross_section:
                    continue
                if float(aligned["score"].std(ddof=0)) <= _EPS or float(
                    aligned["forward"].std(ddof=0)
                ) <= _EPS:
                    continue
                rows.append(
                    {
                        "timestamp": pd.Timestamp(timestamp),
                        "realized_at": pd.Timestamp(
                            close.index[close.index.get_loc(timestamp) + horizon]
                        ),
                        "factor": factor,
                        "horizon": int(horizon),
                        "ic": float(aligned["score"].corr(aligned["forward"], method="pearson")),
                        "rank_ic": float(aligned["score"].corr(aligned["forward"], method="spearman")),
                        "n": len(aligned),
                    }
                )
    if not rows:
        return pd.DataFrame(
            columns=["realized_at", "factor", "horizon", "ic", "rank_ic", "n"]
        )
    return pd.DataFrame(rows).set_index("timestamp").sort_index()


def summarize_information_coefficients(ic_series: pd.DataFrame) -> pd.DataFrame:
    if ic_series.empty:
        return pd.DataFrame(
            columns=["mean_ic", "mean_rank_ic", "ic_ir", "rank_ic_ir", "positive_ic_rate", "observations"]
        )
    rows: list[dict[str, object]] = []
    for (factor, horizon), group in ic_series.groupby(["factor", "horizon"]):
        ic_std = float(group["ic"].std(ddof=1))
        rank_std = float(group["rank_ic"].std(ddof=1))
        rows.append(
            {
                "factor": factor,
                "horizon": int(horizon),
                "mean_ic": float(group["ic"].mean()),
                "mean_rank_ic": float(group["rank_ic"].mean()),
                "ic_ir": float(group["ic"].mean() / ic_std) if ic_std > _EPS else 0.0,
                "rank_ic_ir": float(group["rank_ic"].mean() / rank_std) if rank_std > _EPS else 0.0,
                "positive_ic_rate": float((group["ic"] > 0.0).mean()),
                "observations": len(group),
            }
        )
    return pd.DataFrame(rows).set_index(["factor", "horizon"]).sort_index()


def factor_decay_table(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    return summary["mean_rank_ic"].unstack("horizon").sort_index()


def average_factor_correlation(factor_panel: pd.DataFrame, min_cross_section: int = 3) -> pd.DataFrame:
    if factor_panel.empty:
        return pd.DataFrame()
    correlations: list[pd.DataFrame] = []
    for timestamp in factor_panel.index.get_level_values("timestamp").unique():
        snapshot = (
            factor_panel.xs(timestamp, level="timestamp")["score"]
            .unstack("factor")
            .dropna(how="all")
        )
        if len(snapshot) < min_cross_section:
            continue
        correlations.append(snapshot.corr(method="spearman"))
    if not correlations:
        return pd.DataFrame()
    factors = sorted(set().union(*(frame.columns for frame in correlations)))
    aligned = [frame.reindex(index=factors, columns=factors) for frame in correlations]
    values = np.nanmean(np.stack([frame.to_numpy(dtype=float) for frame in aligned]), axis=0)
    return pd.DataFrame(values, index=factors, columns=factors)


def factor_rank_turnover(factor_panel: pd.DataFrame) -> pd.Series:
    """Mean absolute change in percentile rank between consecutive factor snapshots."""

    if factor_panel.empty:
        return pd.Series(dtype=float, name="rank_turnover")
    result: dict[str, float] = {}
    factors = factor_panel.index.get_level_values("factor").unique()
    for factor in factors:
        matrix = factor_panel.xs(factor, level="factor")["score"].unstack("symbol").sort_index()
        ranks = matrix.rank(axis=1, pct=True)
        changes: list[float] = []
        for i in range(1, len(ranks)):
            pair = pd.concat([ranks.iloc[i - 1], ranks.iloc[i]], axis=1).dropna()
            if len(pair) >= 2:
                changes.append(float((pair.iloc[:, 1] - pair.iloc[:, 0]).abs().mean()))
        result[str(factor)] = float(np.mean(changes)) if changes else float("nan")
    return pd.Series(result, name="rank_turnover").sort_index()


def orthogonalize_factor_panel(factor_panel: pd.DataFrame) -> pd.DataFrame:
    """Sequentially residualize factor scores cross-sectionally in deterministic order."""

    if factor_panel.empty:
        return factor_panel.copy()
    preferred_order = [
        "momentum_252_21",
        "momentum_63_5",
        "short_reversal_5",
        "low_volatility_60",
        "low_beta_126",
        "liquidity_20",
        "volume_surprise_5_20",
    ]
    present = list(factor_panel.index.get_level_values("factor").unique())
    order = [factor for factor in preferred_order if factor in present]
    order.extend(sorted(factor for factor in present if factor not in order))
    rows: list[pd.DataFrame] = []
    for timestamp in factor_panel.index.get_level_values("timestamp").unique():
        snapshot = factor_panel.xs(timestamp, level="timestamp")["score"].unstack("factor")
        timestamp_order = [factor for factor in order if factor in snapshot.columns]
        orthogonal = pd.DataFrame(index=snapshot.index, columns=timestamp_order, dtype=float)
        orthogonal.index.name = "symbol"
        orthogonal.columns.name = "factor"
        completed: list[str] = []
        for factor in timestamp_order:
            residual = snapshot[factor].astype(float).copy()
            for previous in completed:
                pair = pd.concat(
                    [residual.rename("y"), orthogonal[previous].rename("x")], axis=1
                ).dropna()
                if len(pair) < 3 or float(pair["x"].std(ddof=0)) <= _EPS:
                    continue
                x = pair["x"] - pair["x"].mean()
                y = pair["y"] - pair["y"].mean()
                beta = float((x * y).sum() / max(float((x * x).sum()), _EPS))
                residual.loc[pair.index] = pair["y"] - beta * pair["x"]
            active = residual.dropna()
            if len(active) >= 2:
                std = float(active.std(ddof=0))
                orthogonal.loc[active.index, factor] = (
                    (active - active.mean()) / std if std > _EPS else 0.0
                )
            completed.append(factor)
        stacked = orthogonal.stack(future_stack=True).dropna().rename("score").to_frame()
        stacked["timestamp"] = pd.Timestamp(timestamp)
        rows.append(stacked.reset_index())
    result = pd.concat(rows, ignore_index=True)
    return result.set_index(["timestamp", "symbol", "factor"]).sort_index()


def learn_factor_ic_weights(
    ic_series: pd.DataFrame,
    signal_date: pd.Timestamp,
    horizon: int = 5,
    lookback: int = 60,
    min_observations: int = 12,
) -> pd.Series:
    """Learn signed factor weights using only labels fully realized by signal_date."""

    if lookback < 1 or min_observations < 3:
        raise ValueError("invalid factor IC learning window")
    if ic_series.empty:
        return pd.Series(dtype=float)
    available = ic_series[
        (ic_series["horizon"] == horizon)
        & (pd.to_datetime(ic_series["realized_at"]) <= pd.Timestamp(signal_date))
    ]
    if available.empty:
        return pd.Series(dtype=float)
    matrix = available.pivot_table(
        index=available.index, columns="factor", values="rank_ic", aggfunc="last"
    ).sort_index()
    matrix = matrix.iloc[::-max(horizon, 1)].iloc[::-1].tail(lookback)
    scores: dict[str, float] = {}
    for factor in matrix.columns:
        observations = matrix[factor].dropna()
        if len(observations) < min_observations:
            continue
        mean = float(observations.mean())
        std = float(observations.std(ddof=1))
        if std <= _EPS:
            continue
        reliability = len(observations) / (len(observations) + 20.0)
        t_like = mean / std * sqrt(len(observations)) * reliability
        scores[str(factor)] = float(np.clip(t_like, -3.0, 3.0))
    weights = pd.Series(scores, dtype=float)
    scale = float(weights.abs().sum())
    if scale <= _EPS:
        return pd.Series(dtype=float)
    return weights / scale


def factor_alpha_from_precomputed(
    factor_panel: pd.DataFrame,
    ic_series: pd.DataFrame,
    signal_date: pd.Timestamp,
    symbols: list[str],
    horizon: int = 5,
    lookback: int = 60,
    min_observations: int = 12,
) -> FactorAlphaSignal:
    weights = learn_factor_ic_weights(
        ic_series,
        signal_date,
        horizon=horizon,
        lookback=lookback,
        min_observations=min_observations,
    )
    zero = pd.Series(0.0, index=symbols, dtype=float)
    timestamps = factor_panel.index.get_level_values("timestamp") if not factor_panel.empty else []
    if weights.empty or signal_date not in timestamps:
        return FactorAlphaSignal(score=zero, weights=weights)
    snapshot = factor_panel.xs(signal_date, level="timestamp")["score"].unstack("factor")
    common = [factor for factor in weights.index if factor in snapshot.columns]
    if not common:
        return FactorAlphaSignal(score=zero, weights=pd.Series(dtype=float))
    score = snapshot[common].fillna(0.0).mul(weights[common], axis=1).sum(axis=1)
    score = score.reindex(symbols).fillna(0.0)
    active = score[score != 0.0]
    if len(active) >= 2 and float(active.std(ddof=0)) > _EPS:
        score.loc[active.index] = (active - active.mean()) / active.std(ddof=0)
    return FactorAlphaSignal(score=score.clip(-4.0, 4.0), weights=weights[common])


def research_factors(
    data: MarketData,
    sampling_every: int = 5,
    horizons: tuple[int, ...] = (1, 5, 20),
    external_factors: dict[str, pd.DataFrame] | None = None,
) -> FactorResearchResult:
    panel = build_market_factor_panel(data, sampling_every, external_factors)
    close = data.close * data.fx_to_base if data.fx_to_base is not None else data.close
    ic_series = information_coefficient_series(panel, close, horizons=horizons)
    summary = summarize_information_coefficients(ic_series)
    return FactorResearchResult(
        factor_panel=panel,
        ic_series=ic_series,
        summary=summary,
        decay=factor_decay_table(summary),
        factor_correlation=average_factor_correlation(panel),
        turnover=factor_rank_turnover(panel),
    )
