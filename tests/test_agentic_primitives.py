"""Tests for whitelisted causal operators and primitive evaluation adapters."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_fund_lab.agentic.primitives import (
    CANONICAL_LOOKBACKS,
    OPERATOR_REGISTRY,
    abs_val,
    clip,
    cs_demean,
    cs_percentile,
    cs_rank,
    cs_zscore,
    evaluate_primitive,
    sign,
    ts_decay_linear,
    ts_delta,
    ts_mean,
    ts_std,
    ts_zscore,
    where,
)


@pytest.fixture
def sample_panel() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=10, freq="B")
    data = {
        "AAPL": [100.0, 102.0, 101.0, 105.0, 107.0, 106.0, 108.0, 110.0, 109.0, 112.0],
        "MSFT": [200.0, 201.0, 203.0, 202.0, 205.0, 207.0, 206.0, 208.0, 211.0, 215.0],
        "GOOG": [150.0, 149.0, 151.0, 153.0, 152.0, 155.0, 158.0, 157.0, 160.0, 162.0],
    }
    return pd.DataFrame(data, index=dates)


def test_canonical_lookbacks_and_registry() -> None:
    assert CANONICAL_LOOKBACKS == frozenset({5, 10, 21, 63, 126, 252})
    expected_ops = {
        "cs_rank", "cs_percentile", "cs_zscore", "cs_demean",
        "ts_mean", "ts_std", "ts_zscore", "ts_delta", "ts_decay_linear",
        "where", "clip", "abs_val", "sign",
    }
    assert set(OPERATOR_REGISTRY.keys()) == expected_ops
    assert len(OPERATOR_REGISTRY) == 13
    for name, op in OPERATOR_REGISTRY.items():
        assert callable(op), f"Operator {name} must be callable"


def test_cs_rank_and_percentile() -> None:
    df = pd.DataFrame({
        "A": [10.0, 10.0, np.nan],
        "B": [20.0, 10.0, 10.0],
        "C": [30.0, 20.0, 20.0],
    })

    # cs_rank
    rnk = cs_rank(df)
    assert isinstance(rnk, pd.DataFrame)
    assert rnk.shape == df.shape
    # Row 0: ranks 1, 2, 3 -> (rank - 1)/(3-1) - 0.5 = [-0.5, 0.0, 0.5]
    np.testing.assert_allclose(rnk.iloc[0].to_numpy(), [-0.5, 0.0, 0.5])
    assert np.isclose(rnk.iloc[0].sum(), 0.0)

    # Row 1 ties: A=10, B=10, C=20 -> ranks 1.5, 1.5, 3 -> [-0.25, -0.25, 0.5]
    np.testing.assert_allclose(rnk.iloc[1].to_numpy(), [-0.25, -0.25, 0.5])
    assert np.isclose(rnk.iloc[1].sum(), 0.0)

    # Row 2 with NaN: B=10, C=20 -> count 2 -> [-0.5, 0.5]
    assert np.isnan(rnk.iloc[2]["A"])
    np.testing.assert_allclose(rnk.iloc[2][["B", "C"]].to_numpy(), [-0.5, 0.5])

    # cs_percentile
    pct = cs_percentile(df)
    assert isinstance(pct, pd.DataFrame)
    np.testing.assert_allclose(pct.iloc[0].to_numpy(), [0.0, 0.5, 1.0])
    np.testing.assert_allclose(pct.iloc[1].to_numpy(), [0.25, 0.25, 1.0])

    # np.ndarray compatibility
    arr = df.to_numpy()
    rnk_arr = cs_rank(arr)
    assert isinstance(rnk_arr, np.ndarray)
    np.testing.assert_allclose(rnk_arr[0], [-0.5, 0.0, 0.5])


def test_cs_zscore() -> None:
    df = pd.DataFrame({
        "A": [10.0, 5.0, 100.0],
        "B": [20.0, 5.0, 10.0],
        "C": [30.0, 5.0, 10.0],
    })
    z = cs_zscore(df)
    assert isinstance(z, pd.DataFrame)
    # Row 0: mean 20, std 10 -> [-1, 0, 1]
    np.testing.assert_allclose(z.iloc[0].to_numpy(), [-1.0, 0.0, 1.0], atol=1e-5)
    # Row 1: zero variance -> zero z-score
    np.testing.assert_allclose(z.iloc[1].to_numpy(), [0.0, 0.0, 0.0], atol=1e-5)
    # Winsorization check: bounded within [-3, 3]
    assert (z >= -3.0).all().all() and (z <= 3.0).all().all()


def test_cs_demean() -> None:
    df = pd.DataFrame({
        "A": [10.0, 20.0],
        "B": [20.0, 30.0],
        "C": [30.0, 40.0],
        "D": [40.0, 50.0],
    })
    # Overall demean
    dem = cs_demean(df)
    np.testing.assert_allclose(dem.mean(axis=1).to_numpy(), [0.0, 0.0], atol=1e-12)

    # Sector demean
    groups = pd.Series({"A": "SEC1", "B": "SEC1", "C": "SEC2", "D": "SEC2"})
    dem_grp = cs_demean(df, group=groups)
    # Group SEC1: mean of A and B is 15 -> A: -5, B: 5
    np.testing.assert_allclose(dem_grp.iloc[0][["A", "B"]].to_numpy(), [-5.0, 5.0])
    # Group SEC2: mean of C and D is 35 -> C: -5, D: 5
    np.testing.assert_allclose(dem_grp.iloc[0][["C", "D"]].to_numpy(), [-5.0, 5.0])


def test_ts_mean_and_std_and_zscore(sample_panel: pd.DataFrame) -> None:
    d = 5
    mean = ts_mean(sample_panel, d)
    std = ts_std(sample_panel, d)
    z = ts_zscore(sample_panel, d)

    assert mean.shape == sample_panel.shape
    assert std.shape == sample_panel.shape
    assert z.shape == sample_panel.shape

    # First d-1 bars: min_periods is max(2, int(0.75*5)) = max(2, 3) = 3
    # So index 0 and 1 must be NaN, index 2+ valid
    assert mean.iloc[0].isna().all()
    assert mean.iloc[1].isna().all()
    assert mean.iloc[2].notna().all()

    # Verify zscore bounded in [-4.0, 4.0]
    valid_z = z.dropna()
    assert (valid_z >= -4.0).all().all() and (valid_z <= 4.0).all().all()


def test_ts_delta(sample_panel: pd.DataFrame) -> None:
    delta = ts_delta(sample_panel, 2)
    assert delta.iloc[0].isna().all()
    assert delta.iloc[1].isna().all()
    # At index 2: row 2 minus row 0
    np.testing.assert_allclose(
        delta.iloc[2].to_numpy(),
        (sample_panel.iloc[2] - sample_panel.iloc[0]).to_numpy(),
    )


def test_ts_decay_linear() -> None:
    df = pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0, 5.0]})
    # d = 3: weights are [1, 2, 3] / 6
    decay = ts_decay_linear(df, 3)
    assert np.isnan(decay.iloc[0, 0])
    assert np.isnan(decay.iloc[1, 0])
    # at index 2 (1, 2, 3): (1*1 + 2*2 + 3*3)/6 = 14/6 = 2.3333333
    assert np.isclose(decay.iloc[2, 0], 14.0 / 6.0)
    # at index 3 (2, 3, 4): (2*1 + 3*2 + 4*3)/6 = 20/6 = 3.3333333
    assert np.isclose(decay.iloc[3, 0], 20.0 / 6.0)


def test_conditional_and_math() -> None:
    df = pd.DataFrame({"A": [1.0, -2.0, 3.0], "B": [-4.0, 5.0, -6.0]})
    cond = df > 0
    w = where(cond, 10.0, -10.0)
    assert isinstance(w, pd.DataFrame)
    np.testing.assert_allclose(w.to_numpy(), [[10.0, -10.0], [-10.0, 10.0], [10.0, -10.0]])

    cl = clip(df, -2.0, 2.0)
    assert isinstance(cl, pd.DataFrame)
    np.testing.assert_allclose(cl.to_numpy(), [[1.0, -2.0], [-2.0, 2.0], [2.0, -2.0]])

    av = abs_val(df)
    assert isinstance(av, pd.DataFrame)
    np.testing.assert_allclose(av.to_numpy(), [[1.0, 4.0], [2.0, 5.0], [3.0, 6.0]])

    sg = sign(df)
    assert isinstance(sg, pd.DataFrame)
    np.testing.assert_allclose(sg.to_numpy(), [[1.0, -1.0], [-1.0, 1.0], [1.0, -1.0]])


def test_evaluate_primitive_models() -> None:
    dates = pd.date_range("2023-01-01", periods=80, freq="B")
    np.random.seed(42)
    symbols = ["AAPL", "MSFT", "GOOG"]
    close = pd.DataFrame(
        np.cumprod(1 + np.random.randn(80, 3) * 0.01, axis=0) * 100,
        index=dates,
        columns=symbols,
    )
    vol = pd.DataFrame(
        np.random.randint(1000, 5000, size=(80, 3)),
        index=dates,
        columns=symbols,
    )

    # 1. KalmanTrend
    kalman_res = evaluate_primitive("KalmanTrend", {}, close)
    assert isinstance(kalman_res, pd.DataFrame)
    assert kalman_res.shape == close.shape
    assert (kalman_res.index == close.index).all()
    assert (kalman_res.columns == close.columns).all()
    assert (kalman_res.iloc[:25] == 0.0).all().all()

    # 2. OUMeanReversion
    ou_res = evaluate_primitive("OUMeanReversion", {"lookback": 60}, close)
    assert isinstance(ou_res, pd.DataFrame)
    assert ou_res.shape == close.shape

    # 3. ResidualMomentum
    res_mom = evaluate_primitive("ResidualMomentum", {"lookback": 60}, close)
    assert isinstance(res_mom, pd.DataFrame)
    assert res_mom.shape == close.shape

    # 4. RollingStat
    r_stat = evaluate_primitive("RollingStat", {"stat": "mean", "window": 10}, close, volume=vol)
    assert isinstance(r_stat, pd.DataFrame)
    assert r_stat.shape == close.shape

    r_stat_vol = evaluate_primitive("RollingStat", {"stat": "delta", "window": 5, "field": "volume"}, close, volume=vol)
    assert isinstance(r_stat_vol, pd.DataFrame)
    assert r_stat_vol.shape == close.shape

    # 5. FundamentalRatio
    fund_res = evaluate_primitive("FundamentalRatio", {"ratio": "pe_ratio"}, close)
    assert isinstance(fund_res, pd.DataFrame)
    assert (fund_res == 0.0).all().all()

    # Invalid module
    with pytest.raises(ValueError, match="Unsupported primitive module_type"):
        evaluate_primitive("InvalidModuleType", {}, close)
