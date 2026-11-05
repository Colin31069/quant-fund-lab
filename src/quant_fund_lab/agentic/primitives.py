"""Whitelisted causal operator library and primitive evaluation adapters.

Provides vectorized cross-sectional, time-series, and mathematical operators
for 2D panels (Dates x Tickers) of shape (T x N).
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

from quant_fund_lab.models import _kalman_path, residual_momentum_alpha

CANONICAL_LOOKBACKS: frozenset[int] = frozenset({5, 10, 21, 63, 126, 252})


def _to_frame(x: Any) -> tuple[pd.DataFrame, str]:
    if isinstance(x, pd.DataFrame):
        return x, "df"
    if isinstance(x, pd.Series):
        return x.to_frame(), "series"
    return pd.DataFrame(x), "ndarray"


def _from_frame(df: pd.DataFrame, orig_type: str) -> Any:
    if orig_type == "df":
        return df
    if orig_type == "series":
        return df.iloc[:, 0]
    return df.to_numpy()


# --- Cross-Sectional Operators (axis=1) ---


def cs_rank(x: Any) -> Any:
    """Centered uniform rank in [-0.5, +0.5] over active/non-NaN items."""
    df, orig = _to_frame(x)
    ranks = df.rank(axis=1, method="average", na_option="keep")
    counts = df.notna().sum(axis=1)
    denom = np.maximum(counts - 1, 1)
    res = ranks.sub(1.0, axis=0).div(denom, axis=0).sub(0.5, axis=0)
    return _from_frame(res.where(counts > 0, np.nan), orig)


def cs_percentile(x: Any) -> Any:
    """Uncentered rank in [0.0, 1.0]. Formula: (rank - 1) / max(count - 1, 1)."""
    df, orig = _to_frame(x)
    ranks = df.rank(axis=1, method="average", na_option="keep")
    counts = df.notna().sum(axis=1)
    denom = np.maximum(counts - 1, 1)
    res = ranks.sub(1.0, axis=0).div(denom, axis=0)
    return _from_frame(res.where(counts > 0, np.nan), orig)


def cs_zscore(x: Any) -> Any:
    """Cross-sectional z-score (mean=0, std=1), Winsorized at [-3.0, +3.0] with eps=1e-8."""
    df, orig = _to_frame(x)
    mean = df.mean(axis=1)
    std = df.std(axis=1, ddof=1).fillna(0.0)
    res = df.sub(mean, axis=0).div(std + 1e-8, axis=0).clip(-3.0, 3.0)
    return _from_frame(res, orig)


def cs_demean(x: Any, group: Any = None) -> Any:
    """Subtract cross-sectional mean (or group mean if group provided)."""
    df, orig = _to_frame(x)
    if group is None:
        return _from_frame(df.sub(df.mean(axis=1), axis=0), orig)
    res = df.copy()
    grp = pd.Series(group, index=df.columns) if not isinstance(group, (pd.DataFrame, pd.Series)) else group
    if isinstance(grp, pd.Series):
        for g in grp.dropna().unique():
            cols = grp[grp == g].index.intersection(df.columns)
            res[cols] = df[cols].sub(df[cols].mean(axis=1), axis=0)
    elif isinstance(grp, pd.DataFrame):
        for t in df.index:
            row_v, row_g = df.loc[t], grp.loc[t]
            for g in row_g.dropna().unique():
                cols = row_g[row_g == g].index
                res.loc[t, cols] = row_v[cols] - row_v[cols].mean()
    return _from_frame(res, orig)


# --- Time-Series Operators (axis=0) ---


def ts_mean(x: Any, d: int) -> Any:
    """Rolling mean over d bars with min_periods = max(2, int(0.75 * d))."""
    df, orig = _to_frame(x)
    return _from_frame(df.rolling(d, min_periods=max(2, int(0.75 * d))).mean(), orig)


def ts_std(x: Any, d: int) -> Any:
    """Rolling sample std over d bars (ddof=1) with min_periods = max(2, int(0.75 * d))."""
    df, orig = _to_frame(x)
    return _from_frame(df.rolling(d, min_periods=max(2, int(0.75 * d))).std(ddof=1), orig)


def ts_zscore(x: Any, d: int) -> Any:
    """clip((x - ts_mean(x, d)) / (ts_std(x, d) + 1e-8), -4.0, 4.0)."""
    df, orig = _to_frame(x)
    m, s = ts_mean(df, d), ts_std(df, d)
    return _from_frame(((df - m) / (s + 1e-8)).clip(-4.0, 4.0), orig)


def ts_delta(x: Any, d: int) -> Any:
    """x_t - x_{t-d}."""
    df, orig = _to_frame(x)
    return _from_frame(df.diff(d), orig)


def ts_decay_linear(x: Any, d: int) -> Any:
    """Linearly weighted moving average with weights (d, d-1, ..., 1) normalized by sum."""
    df, orig = _to_frame(x)
    w = np.arange(1, d + 1, dtype=float)
    w /= w.sum()
    return _from_frame(df.rolling(d).apply(lambda s: np.dot(s, w), raw=True), orig)


# --- Conditional & Math Operators ---


def where(cond: Any, x: Any, y: Any) -> Any:
    """np.where(cond, x, y) preserving DataFrame/Series structure."""
    tpl = next((obj for obj in (x, y, cond) if isinstance(obj, (pd.DataFrame, pd.Series))), None)
    c = cond.to_numpy() if isinstance(cond, (pd.DataFrame, pd.Series)) else np.asarray(cond)
    xa = x.to_numpy() if isinstance(x, (pd.DataFrame, pd.Series)) else np.asarray(x)
    ya = y.to_numpy() if isinstance(y, (pd.DataFrame, pd.Series)) else np.asarray(y)
    res = np.where(c, xa, ya)
    if isinstance(tpl, pd.DataFrame):
        return pd.DataFrame(res, index=tpl.index, columns=tpl.columns)
    if isinstance(tpl, pd.Series):
        return pd.Series(res, index=tpl.index)
    return res


def clip(x: Any, low: float, high: float) -> Any:
    """np.clip(x, low, high) preserving structure."""
    if np.isscalar(x):
        return float(np.clip(x, low, high))
    df, orig = _to_frame(x)
    return _from_frame(df.clip(lower=low, upper=high), orig)


def abs_val(x: Any) -> Any:
    """np.abs(x) preserving structure."""
    if np.isscalar(x):
        return abs(x)
    df, orig = _to_frame(x)
    return _from_frame(df.abs(), orig)


def sign(x: Any) -> Any:
    """np.sign(x) preserving structure."""
    if np.isscalar(x):
        return float(np.sign(x))
    df, orig = _to_frame(x)
    return _from_frame(np.sign(df), orig)


OPERATOR_REGISTRY: dict[str, Callable[..., Any]] = {
    "cs_rank": cs_rank, "cs_percentile": cs_percentile, "cs_zscore": cs_zscore,
    "cs_demean": cs_demean, "ts_mean": ts_mean, "ts_std": ts_std,
    "ts_zscore": ts_zscore, "ts_delta": ts_delta, "ts_decay_linear": ts_decay_linear,
    "where": where, "clip": clip, "abs_val": abs_val, "sign": sign,
}


# --- Primitive Evaluation Adapter ---


def evaluate_primitive(
    module_type: str,
    params: dict[str, Any],
    close: pd.DataFrame,
    volume: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Adapt calls to models functions or rolling statistics, returning (T x N) panel."""
    norm = module_type.lower().replace("_", "")
    out = pd.DataFrame(0.0, index=close.index, columns=close.columns, dtype=float)

    if "kalman" in norm:
        for col in close.columns:
            s = close[col].dropna()
            if len(s) >= 30:
                logp = np.log(s.to_numpy(dtype=float))
                _, tr = _kalman_path(logp)
                vol = (
                    pd.Series(np.diff(logp), index=range(1, len(s)))
                    .rolling(59, min_periods=2).std(ddof=1).reindex(range(len(s))).fillna(0.0).to_numpy()
                )
                sc = np.clip(tr / np.maximum(vol, 1e-4), -4.0, 4.0)
                sc[:29] = 0.0
                out.loc[s.index, col] = sc
        return out

    if "ou" in norm or "reversion" in norm:
        lb = int(params.get("lookback", 60))
        min_obs = max(35, lb // 2)
        for col in close.columns:
            s = close[col].dropna()
            if len(s) >= min_obs:
                logp = np.log(s.to_numpy(dtype=float))
                lev, _ = _kalman_path(logp)
                res = logp - lev
                for i in range(min_obs, len(res)):
                    x = res[max(0, i - lb + 1) : i + 1]
                    des = np.column_stack([np.ones(len(x) - 1), x[:-1]])
                    intercept, phi = np.linalg.lstsq(des, x[1:], rcond=None)[0]
                    if 0.0 < phi < 0.995:
                        kappa, mean_lr = -np.log(phi), intercept / (1.0 - phi)
                        sig = float(np.std(x[1:] - (intercept + phi * x[:-1]), ddof=1))
                        z = (x[-1] - mean_lr) / max(sig, 1e-5)
                        out.loc[s.index[i], col] = float(np.clip(-z * min(kappa / 0.05, 2.0), -4.0, 4.0))
        return out

    if "residual" in norm or "momentum" in norm:
        lb = int(params.get("lookback", 60))
        for i in range(21, len(close)):
            out.iloc[i] = residual_momentum_alpha(close.iloc[: i + 1], lookback=lb)
        return out

    if "rollingstat" in norm or "stat" in norm:
        stat = str(params.get("stat", params.get("statistic", "mean"))).lower()
        w = int(params.get("window", params.get("lookback", params.get("d", 21))))
        field = str(params.get("field", "close")).lower()
        tgt = volume if (field == "volume" and volume is not None) else close
        dispatch = {"mean": ts_mean, "std": ts_std, "zscore": ts_zscore, "delta": ts_delta, "decay_linear": ts_decay_linear}
        if stat in dispatch:
            res = dispatch[stat](tgt, w)
            return res if isinstance(res, pd.DataFrame) else pd.DataFrame(res, index=close.index, columns=close.columns)
        raise ValueError(f"Unknown rolling statistic: {stat}")

    if "fundamental" in norm or "ratio" in norm:
        return out

    raise ValueError(f"Unsupported primitive module_type: {module_type}")


__all__ = [
    "CANONICAL_LOOKBACKS", "OPERATOR_REGISTRY", "abs_val", "clip",
    "cs_demean", "cs_percentile", "cs_rank", "cs_zscore", "evaluate_primitive",
    "sign", "ts_decay_linear", "ts_delta", "ts_mean", "ts_std", "ts_zscore", "where",
]
