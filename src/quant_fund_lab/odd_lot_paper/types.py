"""Immutable session-boundary state before introducing durable odd-lot accounts."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date


def _number(value: float, *, nonnegative: bool = True) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("state values must be finite numbers")
    if nonnegative and value < 0:
        raise ValueError("state value cannot be negative")


def _day(value: str) -> None:
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("session dates must use canonical ISO dates")


def _quantity(value: int, *, positive: bool = True) -> None:
    if type(value) is not int or value < (1 if positive else 0):
        raise ValueError("share/session quantities must be explicit integers")


@dataclass(frozen=True)
class StopState:
    symbol: str
    stop: float
    high_close: float
    distance: float

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("stop requires a symbol")
        for value in (self.stop, self.high_close, self.distance):
            _number(value)
        if self.distance >= 1:
            raise ValueError("stop distance must be below one")


@dataclass(frozen=True)
class PendingOrder:
    symbol: str
    side: str
    quantity: int
    reason: str
    stop: float = 0.0
    signal_price: float = 0.0
    distance: float = 0.0
    signal_volume: float = 0.0

    def __post_init__(self) -> None:
        if not self.symbol or self.side not in {"BUY", "SELL"} or not self.reason:
            raise ValueError("pending order requires symbol, side and reason")
        _quantity(self.quantity)
        for value in (self.stop, self.signal_price, self.distance, self.signal_volume):
            _number(value)
        if self.distance >= 1:
            raise ValueError("order distance must be below one")


@dataclass(frozen=True)
class TradeSettlement:
    trade_date: str
    symbol: str
    side: str
    amount: float
    remaining_sessions: int
    settled_at: str | None = None

    def __post_init__(self) -> None:
        _day(self.trade_date)
        _number(self.amount, nonnegative=self.side == "BUY")
        _quantity(self.remaining_sessions, positive=False)
        if not self.symbol or self.side not in {"BUY", "SELL"}:
            raise ValueError("settlement requires symbol and side")
        if self.settled_at is not None:
            _day(self.settled_at)
            if self.settled_at < self.trade_date or self.remaining_sessions:
                raise ValueError("settled obligation has inconsistent timing")
        elif self.remaining_sessions == 0:
            raise ValueError("unsettled obligation must retain future session count")


@dataclass(frozen=True)
class FractionalReceivable:
    symbol: str
    fractional_quantity: float
    settlement_date: str
    local_currency: str

    def __post_init__(self) -> None:
        _day(self.settlement_date)
        _number(self.fractional_quantity)
        if not self.symbol or not self.local_currency or not 0 < self.fractional_quantity < 1:
            raise ValueError("fractional receivable requires a positive fractional share")


@dataclass(frozen=True)
class OddLotSessionState:
    """After NAV, before next close signal; cash already reserves buy obligations.

    This does not invent cost-basis fields absent from PortfolioState. Episode
    accounting continues to derive cost and realized PnL from cumulative events.
    """

    session: str
    origin_session: str
    session_offset: int
    cash: float
    shares: tuple[tuple[str, int], ...] = ()
    receivable_value: float = 0.0
    stops: tuple[StopState, ...] = ()
    pending: tuple[PendingOrder, ...] = ()
    terminated: tuple[str, ...] = ()
    receivables: tuple[FractionalReceivable, ...] = ()
    settlements: tuple[TradeSettlement, ...] = ()
    passive_submitted: bool = False
    schema_version: int = 1

    def __post_init__(self) -> None:
        _day(self.session)
        _day(self.origin_session)
        _quantity(self.session_offset, positive=False)
        _number(self.cash)
        _number(self.receivable_value)
        if self.origin_session > self.session or type(self.passive_submitted) is not bool:
            raise ValueError("invalid session origin or passive-entry flag")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported session state schema")
        for name in ("shares", "stops", "pending", "terminated", "receivables", "settlements"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError("session state collections must be immutable tuples")
        if any(not isinstance(row, tuple) or len(row) != 2 for row in self.shares):
            raise TypeError("positions must be immutable symbol/quantity pairs")
        if any(not isinstance(symbol, str) or not symbol for symbol in self.terminated):
            raise ValueError("terminated symbols must be nonempty strings")
        for symbol, quantity in self.shares:
            if not symbol:
                raise ValueError("position requires symbol")
            _quantity(quantity, positive=False)
        for rows, expected in ((self.stops, StopState), (self.pending, PendingOrder),
                               (self.receivables, FractionalReceivable),
                               (self.settlements, TradeSettlement)):
            if any(not isinstance(row, expected) for row in rows):
                raise TypeError("session state requires typed records")
        keys = [[row[0] for row in self.shares], [row.symbol for row in self.stops],
                [row.symbol for row in self.pending], list(self.terminated)]
        if any(len(set(values)) != len(values) for values in keys):
            raise ValueError("duplicate session state symbol")
        if any(row.trade_date > self.session or (row.settled_at or self.session) > self.session
               for row in self.settlements):
            raise ValueError("settlement history cannot extend beyond checkpoint")

    def to_dict(self) -> dict:
        return asdict(self)
