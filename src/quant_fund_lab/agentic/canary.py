"""Warmup-aware Canary Perturbation Test for quant_fund_lab agentic strategies."""

from __future__ import annotations

import ast

import numpy as np

from quant_fund_lab.agentic.compiler import CompiledAlphaStrategy
from quant_fund_lab.agentic.schemas import StrategyContract
from quant_fund_lab.data import MarketData

_TS_OPERATORS = frozenset({"ts_mean", "ts_std", "ts_zscore", "ts_delta", "ts_decay_linear"})


class LookAheadError(ValueError):
    """Raised when canary perturbation detects future lookahead leakage."""


def compute_max_warmup_bars(contract: StrategyContract) -> int:
    """Calculate deterministic warmup horizon W_max from primitives and AST lookbacks."""
    w_primitives_list: list[float] = []

    for prim in contract.primitives:
        norm = prim.module_type.lower()
        if "half_life" in prim.params:
            w_primitives_list.append(4.0 * float(prim.params["half_life"]))
        elif "kalman" in norm:
            w_primitives_list.append(30.0)
        elif "ou" in norm or "reversion" in norm:
            w_primitives_list.append(float(prim.params.get("lookback", 60)))
        else:
            w_primitives_list.append(float(prim.params.get("window", prim.params.get("lookback", prim.params.get("d", 21)))))

    w_prim = max(w_primitives_list) if w_primitives_list else 30.0

    # Extract time-series operator lookbacks from AST
    w_ast = 0
    exprs = [contract.signal_expression]
    if contract.regime_gate_expression:
        exprs.append(contract.regime_gate_expression)

    for expr in exprs:
        try:
            tree = ast.parse(expr.strip(), mode="eval")
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if type(node) is ast.Call and type(node.func) is ast.Name and node.func.id in _TS_OPERATORS:
                d_val = None
                if len(node.args) >= 2 and type(node.args[1]) is ast.Constant and type(node.args[1].value) is int:
                    d_val = node.args[1].value
                for kw in node.keywords:
                    if kw.arg == "d" and type(kw.value) is ast.Constant and type(kw.value.value) is int:
                        d_val = kw.value.value
                if d_val is not None:
                    w_ast += d_val

    return int(w_prim + w_ast + 10)


def run_canary_test(strategy: CompiledAlphaStrategy, data: MarketData, seed: int = 42) -> bool:
    """Execute 3-zone canary test asserting clean isolation between assertion and corrupted future."""
    w_max = compute_max_warmup_bars(strategy.contract)
    t_canary = w_max + 60

    if len(data.close) < t_canary:
        raise ValueError(
            f"Canary test requires at least {t_canary} bars (W_max={w_max} + 60), but data only has {len(data.close)} bars."
        )

    clean_slice = data.slice(end=data.close.index[t_canary - 1])

    rng = np.random.default_rng(seed)
    c_close = clean_slice.close.copy()
    c_open = clean_slice.open.copy()
    c_volume = clean_slice.volume.astype(float).copy()

    # Zone 3: [W_max + 30, W_max + 60] (30 bars)
    z3_slice = slice(w_max + 30, w_max + 60)
    n_tickers = c_close.shape[1]

    # 1. Extreme price shock and cross-sectional column permutation
    price_shock = np.exp(rng.normal(0.8, 1.5, size=(30, n_tickers)))
    c_close.iloc[z3_slice] = c_close.iloc[z3_slice] * price_shock
    c_open.iloc[z3_slice] = c_open.iloc[z3_slice] * price_shock

    perm = rng.permutation(n_tickers)
    c_close.iloc[z3_slice] = c_close.iloc[z3_slice].iloc[:, perm].to_numpy()
    c_open.iloc[z3_slice] = c_open.iloc[z3_slice].iloc[:, perm].to_numpy()

    # 2. Volume explosion
    vol_multiplier = 1000.0 * rng.uniform(0.5, 5.0, size=(30, n_tickers))
    c_volume.iloc[z3_slice] = c_volume.iloc[z3_slice] * vol_multiplier

    # 3. Delisting / halt simulation (30% of universe)
    n_delist = max(1, int(0.30 * n_tickers))
    delist_cols = rng.choice(n_tickers, size=n_delist, replace=False)
    c_close.iloc[z3_slice, delist_cols] = np.nan
    c_open.iloc[z3_slice, delist_cols] = np.nan
    c_volume.iloc[z3_slice, delist_cols] = 0.0

    corrupted_data = MarketData(
        open=c_open,
        close=c_close,
        volume=c_volume,
        base_currency=clean_slice.base_currency,
        exchange=clean_slice.exchange,
    )

    w_base = strategy.precompute_panel(clean_slice)
    w_corrupted = strategy.precompute_panel(corrupted_data)

    # Zone 2 assertion: [W_max, W_max + 30]
    z2_base = w_base.iloc[w_max : w_max + 30]
    z2_corr = w_corrupted.iloc[w_max : w_max + 30]

    max_diff = float((z2_base - z2_corr).abs().to_numpy().max())
    if max_diff > 1e-12:
        raise LookAheadError(
            f"Lookahead leak detected in Canary test: max Zone 2 diff is {max_diff:.2e} > 1e-12"
        )

    # Activity assertion: >= 20% active bars in Zone 2
    active_ratio = float((z2_base.abs().sum(axis=1) > 1e-6).mean())
    if active_ratio < 0.20:
        raise ValueError(
            f"Strategy inactive in Zone 2: only {active_ratio:.1%} bars active (minimum 20% required)"
        )

    return True


__all__ = ["LookAheadError", "compute_max_warmup_bars", "run_canary_test"]
