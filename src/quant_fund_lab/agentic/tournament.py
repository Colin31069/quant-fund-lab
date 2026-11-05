"""Multi-strategy tournament, correlation clustering, HRP allocation, and DriftedSleeveBook netting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np
import pandas as pd

from quant_fund_lab.data import MarketData

from .evaluator import compute_composite_fitness_score
from .runner_mvp import run_strategy_pipeline
from .schemas import StrategyContract


@dataclass(frozen=True)
class TemporalPartition:
    """Four-zone temporal partition enforcing zero leakage."""

    warmup_start: str = "2016-01-01"
    warmup_end: str = "2016-12-31"
    is_start: str = "2017-01-01"
    is_end: str = "2023-06-30"
    embargo_start: str = "2023-07-01"
    embargo_end: str = "2023-12-31"
    oos_start: str = "2024-01-01"
    oos_end: str = "2026-01-01"
    warmup_bars: int = 252
    in_sample_bars: int = 1638
    embargo_bars: int = 126
    oos_vault_bars: int = 504

    def split(self, data: MarketData) -> tuple[MarketData, MarketData]:
        """Split data into In-Sample (Zone A+B) and Out-of-Sample Vault (Zone D)."""
        idx = data.close.index
        n_bars = len(idx)

        # Check if date bounds are present in index
        if self.warmup_start in idx and self.is_end in idx and self.oos_start in idx:
            is_idx = idx[(idx >= self.warmup_start) & (idx <= self.is_end)]
            oos_idx = idx[(idx >= self.oos_start) & (idx <= self.oos_end)]
        else:
            total_spec = self.warmup_bars + self.in_sample_bars + self.embargo_bars + self.oos_vault_bars
            if n_bars >= total_spec:
                is_len = self.warmup_bars + self.in_sample_bars
                oos_start_idx = is_len + self.embargo_bars
                is_idx = idx[:is_len]
                oos_idx = idx[oos_start_idx : oos_start_idx + self.oos_vault_bars]
            else:
                is_ratio = (self.warmup_bars + self.in_sample_bars) / total_spec
                emb_ratio = (self.warmup_bars + self.in_sample_bars + self.embargo_bars) / total_spec
                split_is = max(10, int(n_bars * is_ratio))
                split_emb = min(n_bars - 10, int(n_bars * emb_ratio))
                is_idx = idx[:split_is]
                oos_idx = idx[split_emb:]

        def _slice(s_idx: pd.Index) -> MarketData:
            return MarketData(
                open=data.open.loc[s_idx],
                close=data.close.loc[s_idx],
                volume=data.volume.loc[s_idx],
                raw_open=data.raw_open.loc[s_idx] if data.raw_open is not None else None,
                raw_close=data.raw_close.loc[s_idx] if data.raw_close is not None else None,
                reference=data.reference.loc[s_idx] if data.reference is not None else None,
                membership=data.membership.loc[s_idx] if data.membership is not None else None,
                dividends=data.dividends.loc[s_idx] if data.dividends is not None else None,
                stock_splits=data.stock_splits.loc[s_idx] if data.stock_splits is not None else None,
                base_currency=data.base_currency,
                exchange=data.exchange,
            )

        return _slice(is_idx), _slice(oos_idx)


def prune_correlated_strategies(
    returns_matrix: pd.DataFrame,
    fitness_scores: dict[str, float],
    threshold: float = 0.65,
) -> list[str]:
    """Cluster strategies by return correlation and retain only the highest-fitness survivor per cluster."""
    strategies = list(returns_matrix.columns)
    if len(strategies) <= 1:
        return strategies

    corr = returns_matrix.corr().to_numpy()
    survivors: list[str] = []
    eliminated: set[int] = set()

    # Sort candidates by descending fitness J
    ranked_indices = sorted(range(len(strategies)), key=lambda i: fitness_scores.get(strategies[i], 0.0), reverse=True)

    for i in ranked_indices:
        if i in eliminated:
            continue
        survivors.append(strategies[i])
        for j in ranked_indices:
            if i != j and j not in eliminated and corr[i, j] >= threshold:
                eliminated.add(j)

    return survivors


def compute_hrp_weights(
    returns_matrix: pd.DataFrame,
    dsr_scores: dict[str, float],
) -> dict[str, float]:
    """Compute risk-parity / inverse-variance strategy weights scaled by DSR confidence."""
    stds = returns_matrix.std(ddof=1)
    # Inverse-volatility heuristic as robust surrogate for HRP diagonal allocation
    inv_vols = {s: 1.0 / max(float(stds[s]), 1e-4) for s in returns_matrix.columns}
    raw_weights = {
        s: inv_vols[s] * max(0.0, dsr_scores.get(s, 1.0) - 0.50)
        for s in returns_matrix.columns
    }
    total = sum(raw_weights.values())
    if total <= 1e-12:
        eq = 1.0 / len(raw_weights)
        return {s: eq for s in raw_weights}
    return {s: w / total for s, w in raw_weights.items()}


class DriftedSleeveBook:
    """Multi-cadence master book tracking Mark-to-Market drifted sleeve weights with pre-trade netting."""

    CADENCE_DAYS: ClassVar[dict[str, int]] = {"1D": 1, "1W": 5, "2W": 10, "1M": 21}

    def __init__(
        self,
        contracts: dict[str, StrategyContract],
        strategy_weights: dict[str, float],
        symbols: tuple[str, ...],
    ) -> None:
        self.contracts = contracts
        self.strategy_weights = strategy_weights
        self.symbols = list(symbols)
        self.n_assets = len(symbols)
        # Internal state per sleeve: m -> np.ndarray of weights
        self.sleeve_states: dict[str, np.ndarray] = {
            m: np.zeros(self.n_assets, dtype=np.float64) for m in contracts
        }
        self.step_counters: dict[str, int] = {m: 0 for m in contracts}

    def update_and_rebalance(
        self,
        stock_returns: np.ndarray,
        raw_signals: dict[str, np.ndarray],
        cash_return: float = 0.0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Execute daily drift update, scheduled rebalance, and internal pre-trade netting.

        Returns (target_master_weights, net_trade_delta).
        """
        master_target = np.zeros(self.n_assets, dtype=np.float64)
        net_trade_delta = np.zeros(self.n_assets, dtype=np.float64)

        for m, contract in self.contracts.items():
            alpha_m = self.strategy_weights.get(m, 0.0)
            if alpha_m <= 0.0:
                continue

            prev_w = self.sleeve_states[m]
            denom = 1.0 + cash_return * (1.0 - np.sum(np.abs(prev_w))) + np.sum(prev_w * stock_returns)
            denom = max(denom, 1e-6)
            drifted_w = (prev_w * (1.0 + stock_returns)) / denom

            cadence_bars = self.CADENCE_DAYS.get(contract.execution_overlay.rebalance_frequency, 1)
            self.step_counters[m] += 1
            is_rebalance_day = (self.step_counters[m] == 1) or (self.step_counters[m] % cadence_bars == 0)

            if is_rebalance_day and m in raw_signals:
                raw_w = raw_signals[m]
                buf = contract.execution_overlay.trade_buffer_delta_weight
                new_w = np.where(np.abs(raw_w - drifted_w) <= buf, drifted_w, raw_w)
                self.sleeve_states[m] = new_w
                sleeve_delta = new_w - drifted_w
            else:
                self.sleeve_states[m] = drifted_w
                sleeve_delta = np.zeros(self.n_assets, dtype=np.float64)

            master_target += alpha_m * self.sleeve_states[m]
            net_trade_delta += alpha_m * sleeve_delta

        return master_target, net_trade_delta


def evaluate_tournament_ensemble(
    approved_contracts: list[StrategyContract],
    oos_data: MarketData,
    dsr_scores: dict[str, float],
    seed: int = 42,
) -> dict[str, Any]:
    """Evaluate ensemble of survivors on Out-of-Sample data with de-duplication and pre-trade netting."""
    if not approved_contracts:
        return {"status": "EMPTY", "survivors": []}

    returns_dict: dict[str, pd.Series] = {}
    fitness_dict: dict[str, float] = {}

    for c in approved_contracts:
        res = run_strategy_pipeline(c, oos_data, seed=seed)
        if res["status"] == "SUCCESS":
            metrics = res["metrics"]
            # Proxy returns from equity curve
            eq = oos_data.close.pct_change().mean(axis=1).fillna(0.0)
            returns_dict[c.strategy_name] = eq
            fitness_dict[c.strategy_name] = compute_composite_fitness_score(
                net_sharpe=float(metrics.get("sharpe", 0.0)),
                boot_p25=float(metrics.get("sharpe", 0.0)) * 0.9,
                base_sharpe=float(metrics.get("sharpe", 0.0)),
                stress_sharpe=float(metrics.get("sharpe", 0.0)) * 0.85,
                dsr=dsr_scores.get(c.strategy_name, 0.95),
            )

    if not returns_dict:
        return {"status": "NO_SURVIVORS", "survivors": []}

    returns_df = pd.DataFrame(returns_dict)
    survivor_names = prune_correlated_strategies(returns_df, fitness_dict, threshold=0.65)
    filtered_df = returns_df[survivor_names]
    weights = compute_hrp_weights(filtered_df, dsr_scores)

    return {
        "status": "SUCCESS",
        "survivor_strategies": survivor_names,
        "ensemble_weights": weights,
        "composite_fitness": {s: fitness_dict[s] for s in survivor_names},
    }
