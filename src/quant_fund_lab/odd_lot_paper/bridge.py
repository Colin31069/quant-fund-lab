"""Translate historical engine state at completed-session boundaries without execution."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..corporate_actions import CashInLieuReceivable
from ..execution import PortfolioState
from .engine_records import EngineOrder as _Order
from .engine_records import EngineStop as _Stop
from .types import (
    FractionalReceivable,
    OddLotSessionState,
    PendingOrder,
    StopState,
    TradeSettlement,
)


@dataclass
class HistoricalSessionState:
    """Fresh mutable objects for the historical loop; never aliases a checkpoint."""

    portfolio: PortfolioState
    stops: dict[str, _Stop]
    pending: dict[str, _Order]
    terminated: set[str]
    receivables: list[CashInLieuReceivable]
    settlements: list[dict]
    passive_submitted: bool


def capture_session_state(runtime: HistoricalSessionState, *, session: str,
                          origin_session: str, session_offset: int,
                          completed_index: int) -> OddLotSessionState:
    """Replace global settlement indexes by remaining sessions, not guessed dates."""
    if type(completed_index) is not int or completed_index < 0:
        raise ValueError("completed index must be a nonnegative integer")
    settlements = []
    for row in runtime.settlements:
        settled = row["settled_at"]
        remaining = 0 if settled is not None else row["due_session_index"] - completed_index
        settlements.append(TradeSettlement(str(pd.Timestamp(row["trade_date"]).date()),
            row["symbol"], row["side"], row["amount"], remaining,
            None if settled is None else str(pd.Timestamp(settled).date())))
    return OddLotSessionState(session, origin_session, session_offset,
        runtime.portfolio.cash, tuple(sorted(runtime.portfolio.shares.items())),
        runtime.portfolio.receivable_value,
        tuple(StopState(symbol, row.stop, row.high_close, row.distance)
              for symbol, row in sorted(runtime.stops.items())),
        tuple(PendingOrder(symbol, row.side, row.quantity, row.reason, row.stop,
                           row.signal_price, row.distance, row.signal_volume)
              for symbol, row in sorted(runtime.pending.items())),
        tuple(sorted(runtime.terminated)),
        tuple(FractionalReceivable(row.symbol, row.fractional_quantity,
              str(pd.Timestamp(row.settlement_date).date()), row.local_currency)
              for row in runtime.receivables), tuple(settlements), runtime.passive_submitted)


def restore_session_state(checkpoint: OddLotSessionState, *, completed_index: int) -> HistoricalSessionState:
    """Rebase pending obligations when an incremental window uses different indexes.

    Settled rows are historical evidence; their due index is unused by the engine.
    They use the completed index while preserving actual trade/settlement dates.
    """
    if type(completed_index) is not int or completed_index < 0:
        raise ValueError("completed index must be a nonnegative integer")
    return HistoricalSessionState(
        PortfolioState(checkpoint.cash, dict(checkpoint.shares), checkpoint.receivable_value),
        {row.symbol: _Stop(row.stop, row.high_close, row.distance) for row in checkpoint.stops},
        {row.symbol: _Order(row.side, row.quantity, row.reason, row.stop, row.signal_price,
                           row.distance, row.signal_volume) for row in checkpoint.pending},
        set(checkpoint.terminated),
        [CashInLieuReceivable(row.symbol, row.fractional_quantity,
                             pd.Timestamp(row.settlement_date), row.local_currency)
         for row in checkpoint.receivables],
        [{"trade_date": pd.Timestamp(row.trade_date), "symbol": row.symbol, "side": row.side,
          "amount": row.amount, "settled_at": None if row.settled_at is None else pd.Timestamp(row.settled_at),
          "due_session_index": completed_index + row.remaining_sessions}
         for row in checkpoint.settlements], checkpoint.passive_submitted)
