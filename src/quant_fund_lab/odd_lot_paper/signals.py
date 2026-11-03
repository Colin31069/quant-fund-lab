"""Pure close-signal planning with explicit history cutoff and rebalance origin."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from math import floor
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from ..config import BacktestConfig
from ..execution import PortfolioState
from .engine_records import EngineOrder, EngineStop

if TYPE_CHECKING:
    from ..odd_lot_research import OddLotResearchConfig


@dataclass(frozen=True)
class SignalPlanInput:
    portfolio: PortfolioState
    stops: dict[str, EngineStop]
    pending: dict[str, EngineOrder]
    terminated: frozenset[str]
    research: OddLotResearchConfig
    config: BacktestConfig
    signal_date: pd.Timestamp
    session_offset: int
    history: pd.DataFrame
    membership: pd.Series
    raw_close: pd.Series
    observed_open: pd.Series
    prior_liquidity: pd.Series
    sale_receivables: float
    passive_submitted: bool
    passive_without_risk_estimate: bool = False

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(self.history.columns)


@dataclass(frozen=True)
class SignalPlanResult:
    stops: dict[str, EngineStop]
    pending: dict[str, EngineOrder]
    passive_submitted: bool
    signals: tuple[dict, ...]


def plan_close_signals(inputs: SignalPlanInput) -> SignalPlanResult:
    """Use only history through signal_date; never reset offset at a segment boundary."""
    from ..odd_lot_research import _entry_quantity, _targets

    if (inputs.history.empty or not inputs.history.index.is_monotonic_increasing
            or not inputs.history.index.is_unique or inputs.history.index[-1] != inputs.signal_date):
        raise ValueError("signal history must end exactly at the signal session")
    if type(inputs.session_offset) is not int or inputs.session_offset < 0:
        raise ValueError("signal offset must preserve the nonnegative rebalance origin")
    state = inputs.portfolio
    stops, pending = deepcopy(inputs.stops), deepcopy(inputs.pending)
    terminated = inputs.terminated
    research, config = inputs.research, inputs.config
    signal_date, close_now = inputs.signal_date, inputs.raw_close
    passive_submitted = inputs.passive_submitted
    _passive_without_risk_estimate = inputs.passive_without_risk_estimate
    equity = state.equity(close_now) + inputs.sale_receivables
    signal_rows = []
    # A stop has precedence over every model and is checked daily, not weekly.
    for symbol, stop in list(stops.items()):
        price = float(close_now.get(symbol, np.nan))
        observed = pd.notna(inputs.observed_open[symbol])
        if not observed or not np.isfinite(price) or price <= 0:
            continue
        if price <= stop.stop:
            pending[symbol] = EngineOrder("SELL", state.shares[symbol], "stop")
            signal_rows.append({"timestamp": signal_date, "symbol": symbol, "reason": "stop", "price": price, "stop": stop.stop, "score": np.nan, "weight": 0.0})
        else:
            stop.high_close = max(stop.high_close, price)
            stop.stop = max(stop.stop, stop.high_close * (1.0 - stop.distance))

    rebalance = inputs.session_offset % research.rebalance_every == 0
    if rebalance and (research.strategy != "equal_weight" or not passive_submitted):
        history = inputs.history
        eligible = inputs.membership.copy()
        eligible.loc[eligible.index.intersection(terminated)] = False
        previous = pd.Series({symbol: state.shares.get(symbol, 0) * float(close_now[symbol]) / equity
                              if equity > 0 and pd.notna(close_now[symbol]) else 0.0
                              for symbol in inputs.symbols}, dtype=float)
        scores, weights = _targets(history, eligible, research, config.strategy, previous)
        for symbol in inputs.symbols:
            held = state.shares.get(symbol, 0)
            if symbol in pending and pending[symbol].side == "SELL":
                continue
            if held and weights[symbol] <= 0 and research.strategy != "equal_weight":
                pending[symbol] = EngineOrder("SELL", held, "model_exit")
                signal_rows.append({"timestamp": signal_date, "symbol": symbol, "reason": "model_exit", "price": float(close_now[symbol]), "stop": stops[symbol].stop, "score": float(scores[symbol]), "weight": 0.0})
            elif not held and weights[symbol] > 0:
                price = float(close_now[symbol])
                if _passive_without_risk_estimate:
                    # A declared buy-and-hold ETF benchmark has no stop/risk
                    # sizing, so strategy volatility windows cannot suppress it.
                    distance = stop_price = 0.0
                else:
                    returns = history[symbol].pct_change(fill_method=None).dropna().tail(research.volatility_lookback)
                    if len(returns) < research.volatility_lookback:
                        continue
                    sigma = float(returns.std(ddof=1))
                    if not np.isfinite(sigma):
                        continue
                    distance = float(np.clip(sigma * research.volatility_multiplier, research.min_stop_distance, research.max_stop_distance))
                    stop_price = price * (1.0 - distance)
                known_volume = float(inputs.prior_liquidity[symbol])
                if research.strategy == "equal_weight":
                    qty = min(999, floor(equity * float(weights[symbol]) / price)) if price > 0 else 0
                else:
                    costs = replace(config.tw_costs, sell_tax_bps=research.instrument_rules[symbol]["sell_tax_bps"])
                    qty = _entry_quantity(price, stop_price, known_volume, equity, float(weights[symbol]),
                                          research, costs, research.instrument_rules[symbol]["kind"])
                if qty:
                    pending[symbol] = EngineOrder("BUY", qty, "entry", stop_price, price, distance, known_volume)
                    signal_rows.append({"timestamp": signal_date, "symbol": symbol, "reason": "entry", "price": price, "stop": stop_price, "score": float(scores[symbol]), "weight": float(weights[symbol])})
            elif not held and symbol in pending and pending[symbol].side == "BUY":
                del pending[symbol]
        passive_submitted = True

    return SignalPlanResult(stops, pending, passive_submitted, tuple(signal_rows))
