import numpy as np
import pandas as pd
import pytest

from quant_fund_lab.data import MarketData, synthetic_market_data
from quant_fund_lab.factors import (
    build_market_factor_panel,
    factor_alpha_from_precomputed,
    factor_rank_turnover,
    information_coefficient_series,
    learn_factor_ic_weights,
    orthogonalize_factor_panel,
    research_factors,
    summarize_information_coefficients,
)


def test_market_factor_panel_is_aligned_finite_and_point_in_time():
    data = synthetic_market_data(symbols=("AAA", "BBB", "CCC", "DDD", "EEE"), periods=340, seed=33)
    panel = build_market_factor_panel(data, sampling_every=5)
    assert not panel.empty
    assert panel.index.names == ["timestamp", "symbol", "factor"]
    assert np.isfinite(panel["score"].to_numpy()).all()
    assert {"momentum_252_21", "low_volatility_60", "low_beta_126", "liquidity_20"}.issubset(
        panel.index.get_level_values("factor")
    )

    cutoff = data.close.index[300]
    early = data.slice(end=cutoff)
    early_panel = build_market_factor_panel(early, sampling_every=5)
    full_at_cutoff = panel.loc[panel.index.get_level_values("timestamp") <= cutoff]
    pd.testing.assert_frame_equal(early_panel, full_at_cutoff)


def test_external_factor_must_be_exactly_point_in_time_aligned():
    data = synthetic_market_data(symbols=("AAA", "BBB", "CCC"), periods=100)
    bad = pd.DataFrame(1.0, index=data.close.index[:-1], columns=data.close.columns)
    with pytest.raises(ValueError, match="align exactly"):
        build_market_factor_panel(data, external_factors={"value": bad})


def test_ic_detects_known_cross_sectional_predictor():
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2024-01-02", periods=90)
    symbols = [f"S{i}" for i in range(8)]
    latent = pd.DataFrame(rng.normal(size=(len(dates), len(symbols))), index=dates, columns=symbols)
    future_returns = 0.01 * latent + rng.normal(0.0, 0.001, size=latent.shape)
    close = pd.DataFrame(100.0, index=dates, columns=symbols)
    for i in range(1, len(dates)):
        close.iloc[i] = close.iloc[i - 1] * (1.0 + future_returns.iloc[i - 1])

    rows = []
    for timestamp in dates[:-1]:
        scores = latent.loc[timestamp]
        standardized = (scores - scores.mean()) / scores.std(ddof=0)
        for symbol, score in standardized.items():
            rows.append({"timestamp": timestamp, "symbol": symbol, "factor": "known", "score": score})
    panel = pd.DataFrame(rows).set_index(["timestamp", "symbol", "factor"])
    ic = information_coefficient_series(panel, close, horizons=(1,))
    summary = summarize_information_coefficients(ic)
    assert summary.loc[("known", 1), "mean_ic"] > 0.90
    assert summary.loc[("known", 1), "mean_rank_ic"] > 0.85


def test_factor_turnover_and_full_research_outputs():
    data = synthetic_market_data(symbols=("AAA", "BBB", "CCC", "DDD", "EEE"), periods=340, seed=17)
    result = research_factors(data, sampling_every=10, horizons=(1, 5))
    assert not result.summary.empty
    assert set(result.decay.columns) == {1, 5}
    assert not result.factor_correlation.empty
    assert not result.turnover.empty
    assert result.turnover.between(0.0, 1.0).all()


def test_factor_research_respects_membership_mask():
    data = synthetic_market_data(symbols=("AAA", "BBB", "CCC", "DDD"), periods=300, seed=18)
    membership = data.membership.copy()
    membership.loc[data.close.index[200]:, "DDD"] = False
    masked = MarketData(
        open=data.open,
        close=data.close,
        volume=data.volume,
        reference=data.reference,
        membership=membership,
        terminal_returns=data.terminal_returns,
        dividends=data.dividends,
        stock_splits=data.stock_splits,
    )
    panel = build_market_factor_panel(masked, sampling_every=5)
    after = panel.loc[panel.index.get_level_values("timestamp") >= data.close.index[200]]
    assert "DDD" not in after.index.get_level_values("symbol")


def test_ic_weight_learning_uses_only_fully_realized_labels():
    dates = pd.bdate_range("2025-01-02", periods=40)
    rows = []
    for i, timestamp in enumerate(dates[:30]):
        rows.append(
            {
                "timestamp": timestamp,
                "realized_at": dates[i + 5],
                "factor": "predictive",
                "horizon": 5,
                "ic": 0.2,
                "rank_ic": 0.3 + i * 0.001,
                "n": 10,
            }
        )
        rows.append(
            {
                "timestamp": timestamp,
                "realized_at": dates[i + 5],
                "factor": "noise",
                "horizon": 5,
                "ic": 0.0,
                "rank_ic": (-1.0) ** i * (0.02 + i * 0.0001),
                "n": 10,
            }
        )
    ic = pd.DataFrame(rows).set_index("timestamp")
    before = learn_factor_ic_weights(ic, dates[20], horizon=5, lookback=20, min_observations=3)
    assert "predictive" in before.index
    assert abs(before["predictive"]) > abs(before.get("noise", 0.0))
    future_modified = ic.copy()
    future_modified.loc[future_modified["realized_at"] > dates[20], "rank_ic"] = -0.99
    after = learn_factor_ic_weights(
        future_modified, dates[20], horizon=5, lookback=20, min_observations=3
    )
    pd.testing.assert_series_equal(before, after)


def test_orthogonalized_panel_reduces_duplicate_factor_correlation():
    data = synthetic_market_data(
        symbols=("AAA", "BBB", "CCC", "DDD", "EEE", "FFF"), periods=120, seed=44
    )
    base = pd.DataFrame(
        np.tile(np.arange(6, dtype=float), (120, 1)),
        index=data.close.index,
        columns=data.close.columns,
    )
    panel = build_market_factor_panel(
        data,
        sampling_every=5,
        external_factors={"dup_a": base, "dup_b": base * 2.0 + 1.0},
    )
    orthogonal = orthogonalize_factor_panel(panel)
    timestamp = orthogonal.index.get_level_values("timestamp").max()
    snapshot = orthogonal.xs(timestamp, level="timestamp")["score"].unstack("factor")
    if {"dup_a", "dup_b"}.issubset(snapshot.columns):
        correlation = snapshot[["dup_a", "dup_b"]].corr().iloc[0, 1]
        assert not np.isfinite(correlation) or abs(float(correlation)) < 1e-8


def test_factor_alpha_signal_is_unchanged_by_unrealized_future_data():
    data = synthetic_market_data(
        symbols=("A", "B", "C", "D", "E", "F", "G", "H"), periods=360, seed=51
    )
    cutoff = data.close.index[320]
    full_panel = orthogonalize_factor_panel(build_market_factor_panel(data, sampling_every=1))
    full_ic = information_coefficient_series(full_panel, data.close, horizons=(5,))
    full_signal = factor_alpha_from_precomputed(
        full_panel, full_ic, cutoff, data.symbols, horizon=5, lookback=40, min_observations=8
    )

    truncated = data.slice(end=cutoff)
    truncated_panel = orthogonalize_factor_panel(
        build_market_factor_panel(truncated, sampling_every=1)
    )
    truncated_ic = information_coefficient_series(truncated_panel, truncated.close, horizons=(5,))
    truncated_signal = factor_alpha_from_precomputed(
        truncated_panel,
        truncated_ic,
        cutoff,
        truncated.symbols,
        horizon=5,
        lookback=40,
        min_observations=8,
    )
    pd.testing.assert_series_equal(full_signal.weights, truncated_signal.weights)
    pd.testing.assert_series_equal(full_signal.score, truncated_signal.score)


def test_turnover_empty_panel_is_safe():
    empty = pd.DataFrame(columns=["score"])
    empty.index = pd.MultiIndex.from_arrays([[], [], []], names=["timestamp", "symbol", "factor"])
    assert factor_rank_turnover(empty).empty
