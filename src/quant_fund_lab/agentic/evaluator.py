"""Drawdown extraction, heuristic attribution, and vectorized stationary bootstrap."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .schemas import (
    CompactBacktestDiagnostics,
    CorePerformance,
    DrawdownEpisode,
    ExecutionFrictionDecomposition,
    GlobalDsrContext,
    RegimeConditionedSharpe,
)


@dataclass(frozen=True)
class RawDrawdownEpisode:
    """Raw peak-to-trough-to-recovery boundaries and metrics of a drawdown episode."""

    episode_id: str
    peak_idx: int
    trough_idx: int
    recovery_idx: int | None
    depth_pct: float
    duration_days: int
    recovery_days: int | None


def extract_top_drawdown_episodes(
    net_returns: pd.Series | np.ndarray,
    max_episodes: int = 3,
    min_depth_pct: float = 2.0,
    min_duration_days: int = 5,
) -> list[RawDrawdownEpisode]:
    """Iterative Peak-to-Trough Masking with Tail Re-Anchoring for unrecovered regimes."""
    if isinstance(net_returns, pd.Series):
        r = net_returns.fillna(0.0).to_numpy(dtype=np.float64)
    else:
        r = np.nan_to_num(net_returns, nan=0.0).astype(np.float64)

    equity = np.cumprod(1.0 + r)
    n_bars = len(equity)
    if n_bars < min_duration_days:
        return []

    active_mask = np.ones(n_bars, dtype=bool)
    episodes: list[RawDrawdownEpisode] = []

    for _ in range(max_episodes * 2):
        if len(episodes) >= max_episodes or active_mask.sum() < min_duration_days:
            break

        dd = np.zeros(n_bars, dtype=np.float64)
        padded = np.concatenate(([False], active_mask, [False]))
        starts = np.flatnonzero(padded[1:] & ~padded[:-1])
        ends = np.flatnonzero(~padded[1:] & padded[:-1])

        if len(starts) == 0:
            break

        for s, e in zip(starts, ends):
            seg_eq = equity[s:e]
            seg_hwm = np.maximum.accumulate(seg_eq)
            dd[s:e] = (seg_eq / np.maximum(seg_hwm, 1e-12)) - 1.0

        trough_idx = int(np.argmin(dd))
        depth_pct = float(dd[trough_idx] * 100.0)
        if abs(depth_pct) < min_depth_pct:
            break

        seg_pos = int(np.searchsorted(starts, trough_idx, side="right") - 1)
        if seg_pos < 0 or seg_pos >= len(starts):
            break
        seg_start, seg_end = int(starts[seg_pos]), int(ends[seg_pos])

        zero_dd_candidates = np.flatnonzero(
            np.isclose(dd[seg_start : trough_idx + 1], 0.0, atol=1e-12)
        )
        peak_idx = seg_start + int(zero_dd_candidates[-1]) if len(zero_dd_candidates) else seg_start

        post_trough_eq = equity[trough_idx + 1 : seg_end]
        rec_candidates = np.flatnonzero(post_trough_eq >= equity[peak_idx] * (1.0 - 1e-12))

        if len(rec_candidates) > 0:
            recovery_idx: int | None = trough_idx + 1 + int(rec_candidates[0])
            recovery_days: int | None = recovery_idx - trough_idx
            active_mask[peak_idx : recovery_idx + 1] = False
        else:
            recovery_idx = None
            recovery_days = None
            active_mask[peak_idx : trough_idx + 1] = False

        duration_days = trough_idx - peak_idx
        if duration_days >= min_duration_days:
            episodes.append(
                RawDrawdownEpisode(
                    episode_id=f"DD_{len(episodes) + 1}",
                    peak_idx=peak_idx,
                    trough_idx=trough_idx,
                    recovery_idx=recovery_idx,
                    depth_pct=round(depth_pct, 2),
                    duration_days=duration_days,
                    recovery_days=recovery_days,
                )
            )
    return episodes


def synthesize_drawdown_driver(
    friction_share: float = 0.0,
    beta_corr: float = 0.0,
    mkt_return: float = 0.0,
    rank_ic: float = 0.0,
    mkt_vol_pct: float = 0.5,
    mkt_autocorr: float = 0.0,
    mkt_disp_pct: float = 0.5,
    effective_tick_bps: float = 10.0,
    odd_lot_penalty: float = 0.0,
    episode_turnover: float = 1.0,
    avg_turnover: float = 1.0,
    is_unrecovered: bool = False,
) -> str:
    """Synthesize concise causal driver attribution using a deterministic 3-slot grammar."""
    # Slot 1: Primary Loss Mechanism
    if friction_share >= 0.35:
        slot1 = "Severe turnover friction bleed"
    elif beta_corr > 0.25 and mkt_return < -0.08:
        slot1 = "Unhedged positive market-beta directional drawdown"
    elif rank_ic < -0.03:
        slot1 = "Cross-sectional factor inversion in top-conviction deciles"
    else:
        slot1 = "Adverse idiosyncratic tail move in concentrated positions"

    # Slot 2: Structural Regime State
    if mkt_vol_pct >= 0.80 and mkt_autocorr <= -0.10:
        slot2 = "high-volatility whipsaw regime"
    elif mkt_vol_pct >= 0.80 and mkt_autocorr > -0.10:
        slot2 = "sustained high-volatility directional bear regime"
    elif mkt_disp_pct <= 0.25:
        slot2 = "low cross-sectional dispersion compression"
    else:
        slot2 = "transitional mid-volatility rotational regime"

    # Slot 3: Microstructure / Turnover Amplifier
    if effective_tick_bps >= 25.0 or odd_lot_penalty >= 0.30:
        slot3 = ", compounded by wide discrete tick spreads and illiquid tail fills"
    elif episode_turnover >= 1.35 * max(avg_turnover, 1e-4):
        slot3 = ", compounded by reactive signal churning"
    elif is_unrecovered:
        slot3 = ", leaving an unrecovered structural drawdown at period end"
    else:
        slot3 = ", with normal execution liquidity"

    return f"{slot1} during {slot2}{slot3}"


def compute_stationary_bootstrap_sharpes(
    net_returns: np.ndarray | pd.Series,
    n_boot: int = 2000,
    avg_block_len: int = 20,
    annualization_factor: float = 252.0,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Vectorized Politis & Romano (1994) Stationary Bootstrap."""
    if isinstance(net_returns, pd.Series):
        r = net_returns.dropna().to_numpy(dtype=np.float64)
    else:
        r = np.asarray(net_returns, dtype=np.float64)

    n_bars = r.shape[0]
    if n_bars < avg_block_len:
        return 0.0, 0.0, 0.0

    rng = np.random.default_rng(seed)
    p_reset = 1.0 / float(avg_block_len)

    resets = rng.random((n_boot, n_bars)) < p_reset
    resets[:, 0] = True

    t_grid = np.arange(n_bars, dtype=np.int32)[np.newaxis, :]
    last_reset_col = np.maximum.accumulate(np.where(resets, t_grid, 0), axis=1)

    random_starts = rng.integers(0, n_bars, size=(n_boot, n_bars), dtype=np.int32)
    active_block_start = np.take_along_axis(random_starts, last_reset_col, axis=1)

    boot_indices = (active_block_start + (t_grid - last_reset_col)) % n_bars
    boot_samples = r[boot_indices]

    means = boot_samples.mean(axis=1)
    stds = boot_samples.std(axis=1, ddof=1)
    sharpes = np.where(stds > 1e-12, np.sqrt(annualization_factor) * (means / stds), 0.0)

    p05, p25, p50 = np.quantile(sharpes, [0.05, 0.25, 0.50])
    return float(p05), float(p25), float(p50)


def compute_composite_fitness_score(
    net_sharpe: float,
    boot_p25: float,
    base_sharpe: float,
    stress_sharpe: float,
    dsr: float,
    lambda_cost: float = 1.50,
) -> float:
    """Evaluate Composite Fitness Score J combining statistical rigor and friction penalty."""
    conservative_sharpe = min(net_sharpe, boot_p25)
    cost_drag = max(0.0, base_sharpe - stress_sharpe)
    return float(dsr * conservative_sharpe - lambda_cost * cost_drag)


def build_compact_diagnostics(
    iteration: int,
    global_dsr: GlobalDsrContext,
    core_perf: CorePerformance,
    regime_sharpes: RegimeConditionedSharpe,
    drawdown_episodes: list[DrawdownEpisode],
    friction_decomp: ExecutionFrictionDecomposition,
) -> CompactBacktestDiagnostics:
    """Build standardized, temporally-anonymized CompactBacktestDiagnostics schema."""
    return CompactBacktestDiagnostics(
        iteration=iteration,
        global_dsr_context=global_dsr,
        core_performance=core_perf,
        regime_conditioned_sharpe=regime_sharpes,
        worst_anonymized_drawdown_episodes=drawdown_episodes,
        execution_friction_decomposition_annual_bps=friction_decomp,
    )
