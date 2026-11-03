"""Pure opening-order execution with explicit state and business-event deltas."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING

import pandas as pd

from ..config import BacktestConfig
from ..execution import PortfolioState
from ..odd_lot_execution import fee_breakdown, simulate_limit_order
from .engine_records import EngineOrder, EngineStop
from .sale_limits import OpeningSaleLimits

if TYPE_CHECKING:
    from ..odd_lot_research import OddLotResearchConfig


@dataclass(frozen=True)
class OpeningExecutionInput:
    portfolio: PortfolioState
    stops: dict[str, EngineStop]
    pending: dict[str, EngineOrder]
    symbols: tuple[str, ...]
    research: OddLotResearchConfig
    config: BacktestConfig
    session: pd.Timestamp
    session_index: int
    raw_open: pd.Series
    liquidity: pd.Series
    reference: pd.Series
    sale_limits: OpeningSaleLimits | None = None


@dataclass(frozen=True)
class OpeningExecutionResult:
    portfolio: PortfolioState
    stops: dict[str, EngineStop]
    pending: dict[str, EngineOrder]
    orders: tuple[dict, ...]
    fills: tuple[dict, ...]
    settlements: tuple[dict, ...]


def execute_opening_orders(inputs: OpeningExecutionInput) -> OpeningExecutionResult:
    """Execute sells before buys; positive sale proceeds stay unavailable until T+2."""
    from ..odd_lot_research import _estimated_risk

    state = PortfolioState(inputs.portfolio.cash, dict(inputs.portfolio.shares),
                           inputs.portfolio.receivable_value)
    stops, pending = deepcopy(inputs.stops), deepcopy(inputs.pending)
    research, config, date = inputs.research, inputs.config, inputs.session
    caps = (None if inputs.sale_limits is None else
            inputs.sale_limits.validate_for(state, str(date.date())))
    reference = inputs.reference
    orders, fills, settlements = [], [], []
    for side in ("SELL", "BUY"):
        for symbol in inputs.symbols:
            order = pending.get(symbol)
            if order is None or order.side != side:
                continue
            if (
                side == "BUY"
                and research.strategy != "equal_weight"
                and sum(qty > 0 for qty in state.shares.values()) >= research.max_positions
            ):
                orders.append({"timestamp": date, "symbol": symbol, "side": side,
                               "reason": order.reason, "requested_quantity": order.quantity,
                               "filled_quantity": 0, "expired_quantity": order.quantity,
                               "limit_price": None, "reference_price": float(reference[symbol]),
                               "open_proxy": float(inputs.raw_open[symbol]),
                               "liquidity_proxy": float(inputs.liquidity[symbol]),
                               "status": "expired", "outcome": "position_limit"})
                del pending[symbol]
                continue
            qty = min(state.shares.get(symbol, 0), 999) if side == "SELL" else min(order.quantity, 999)
            executable = min(qty, caps.get(symbol, 0)) if side == "SELL" and caps is not None else qty
            rule = research.instrument_rules[symbol]
            costs = replace(config.tw_costs, sell_tax_bps=rule["sell_tax_bps"])
            fill, limit_price, outcome = simulate_limit_order(
                state, symbol, side, executable, float(inputs.raw_open[symbol]),
                float(inputs.liquidity[symbol]), float(reference[symbol]), date, costs,
                rule, research.limit_offset, research.fill_fraction, research.fee_rounding,
            )
            filled_quantity = 0 if fill is None else fill.quantity
            if side == "SELL" and executable < qty:
                outcome = "not_tradable" if executable == 0 else (
                    "tradability_limited" if filled_quantity == executable else outcome)
            orders.append({"timestamp": date, "symbol": symbol, "side": side,
                           "reason": order.reason, "requested_quantity": qty,
                           "filled_quantity": filled_quantity, "expired_quantity": qty - filled_quantity,
                           "limit_price": limit_price, "reference_price": float(reference[symbol]),
                           "open_proxy": float(inputs.raw_open[symbol]),
                           "liquidity_proxy": float(inputs.liquidity[symbol]),
                           "status": "filled" if filled_quantity == qty and qty else
                                     "partial_expired" if filled_quantity else "expired",
                           "outcome": outcome})
            if side == "BUY":
                # Exchange orders expire daily; no automatic top-up of a partial entry.
                del pending[symbol]
            if fill is None:
                continue
            amount = fill.gross_value + fill.fees if side == "BUY" else fill.gross_value - fill.fees
            if side == "SELL" and amount >= 0:
                # Sell proceeds are an economic receivable until T+2 close.
                state.cash -= amount
            settlements.append({"trade_date": date, "symbol": symbol, "side": side,
                                "amount": amount, "settled_at": None,
                                "due_session_index": inputs.session_index + 2})
            record = asdict(fill)
            record["commission"], record["sell_tax"] = fee_breakdown(
                side, fill.gross_value, costs, research.fee_rounding,
            )
            record["reason"] = order.reason
            record["planned_risk"] = 0.0
            # Freeze the decision-time budget; diagnostics must not infer it
            # from a later configuration or the episode's realized loss.
            record["entry_risk_budget"] = (
                float(research.risk_budget)
                if side == "BUY" and research.strategy != "equal_weight" else None
            )
            if side == "BUY":
                if research.strategy != "equal_weight":
                    record["planned_risk"] = _estimated_risk(
                        fill.quantity, order.signal_price, order.stop, order.signal_volume,
                        costs, rule["kind"], research.fee_rounding,
                    )
                    stops[symbol] = EngineStop(order.stop, order.signal_price, order.distance)
            elif state.shares.get(symbol, 0) <= 0:
                stops.pop(symbol, None)
                del pending[symbol]
            fills.append(record)
    return OpeningExecutionResult(state, stops, pending, tuple(orders), tuple(fills), tuple(settlements))
