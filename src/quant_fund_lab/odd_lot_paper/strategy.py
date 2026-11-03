"""Shared odd-lot research sizing and targets, independent of account storage."""
from __future__ import annotations

from math import floor, sqrt
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from ..config import MarketCostConfig, StrategyConfig
from ..models import ensemble_alpha
from ..odd_lot_execution import round_price, trade_fees
from ..portfolio import optimize_weights
from ..research import detect_market_regime, neutralize_alpha, regime_adjusted_alpha

if TYPE_CHECKING:
    from ..odd_lot_research import OddLotResearchConfig


def _estimated_risk(
    quantity: int, price: float, stop: float, volume: float, costs: MarketCostConfig,
    kind: str = "stock", fee_rounding: str = "fractional",
) -> float:
    if quantity <= 0:
        return 0.0
    impact = costs.impact_coefficient * sqrt(quantity / max(volume, 1.0)) / 100.0
    slip = costs.slippage_bps / 10_000.0 + impact
    buy = quantity * round_price(price * (1.0 + slip), kind, "up")
    exit_price = stop * max(0.0, 1.0 - slip)
    sell = quantity * round_price(exit_price, kind, "down") if exit_price >= 0.01 else 0.0
    return buy + trade_fees("BUY", buy, costs, fee_rounding) - sell + trade_fees("SELL", sell, costs, fee_rounding)


def _entry_quantity(
    price: float, stop: float, volume: float, equity: float, weight: float,
    research: OddLotResearchConfig, costs: MarketCostConfig, kind: str,
) -> int:
    if not np.isfinite(price) or not np.isfinite(stop) or price <= stop or stop <= 0 or volume <= 0:
        return 0
    high = max(0, floor(equity * min(weight, research.max_weight) / price))
    high = min(high, costs.max_order_shares or high)
    low = 0
    while low < high:
        mid = (low + high + 1) // 2
        if _estimated_risk(mid, price, stop, volume, costs, kind, research.fee_rounding) <= research.risk_budget:
            low = mid
        else:
            high = mid - 1
    return low


def _targets(
    history: pd.DataFrame, eligible: pd.Series, research: OddLotResearchConfig,
    strategy: StrategyConfig, previous: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    symbols = history.columns
    eligible = eligible.reindex(symbols).fillna(False).astype(bool)
    if research.strategy == "equal_weight":
        scores = pd.Series(1.0, index=symbols).where(eligible, 0.0)
    elif research.strategy == "momentum":
        if len(history) <= research.momentum_lookback:
            return pd.Series(0.0, index=symbols), pd.Series(0.0, index=symbols)
        scores = (history.iloc[-1] / history.iloc[-research.momentum_lookback - 1] - 1.0)
        scores = scores.replace([np.inf, -np.inf], np.nan).fillna(0.0).where(eligible, 0.0)
    else:
        frame = ensemble_alpha(history, strategy)
        regime = detect_market_regime(history, strategy.regime_lookback)
        scores = regime_adjusted_alpha(frame, strategy, regime) if strategy.regime_enabled else frame["ensemble"]
        returns = history.pct_change(fill_method=None).tail(strategy.factor_lookback)
        if strategy.factor_neutralization:
            neutral, _ = neutralize_alpha(scores, returns, eligible=eligible)
            scores = (1.0 - strategy.factor_neutralization_strength) * scores + strategy.factor_neutralization_strength * neutral
        scores = scores.reindex(symbols).fillna(0.0).where(eligible, 0.0)
    ranked = sorted((str(s) for s in symbols if eligible[s] and scores[s] > 0), key=lambda s: (-float(scores[s]), s))
    selected = ranked if research.strategy == "equal_weight" else ranked[:research.max_positions]
    allowed = pd.Series(False, index=symbols)
    allowed.loc[selected] = True
    if research.strategy == "ensemble" and selected:
        returns = history.pct_change(fill_method=None).tail(strategy.covariance_lookback)
        regime = detect_market_regime(history, strategy.regime_lookback)
        limit = regime.gross_exposure_limit if strategy.regime_enabled else 1.0
        weights = optimize_weights(scores, returns, previous, strategy, eligible=allowed, gross_exposure_limit=limit)
    else:
        weights = pd.Series(0.0, index=symbols)
        if selected:
            denominator = len(selected) if research.strategy == "equal_weight" else research.max_positions
            weights.loc[selected] = min(research.max_weight, 1.0 / denominator)
    return scores, weights


