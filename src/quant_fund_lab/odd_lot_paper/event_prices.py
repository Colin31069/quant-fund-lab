"""Pure ex-event price-level adjustments, preserving pre-event dividend ordering."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class EventPriceInput:
    previous_close: float
    split_ratio: float
    cash_dividend: float
    stop: float | None = None
    high_close: float | None = None


@dataclass(frozen=True)
class EventPriceResult:
    reference: float
    stop: float | None
    high_close: float | None
    cancel_pending_buy: bool


def adjust_event_prices(values: EventPriceInput) -> EventPriceResult:
    """Adjust cash dividends before splits; unknown reference inputs stay unknown.

    Unknown split/dividend values invalidate the matching reference but do not
    fabricate a stop transformation or a tradable zero quote.
    """
    ratio, dividend = values.split_ratio, values.cash_dividend
    split = bool(np.isfinite(ratio) and ratio > 0 and not np.isclose(ratio, 1.0))
    stop, high = values.stop, values.high_close
    if np.isfinite(dividend) and dividend > 0:
        stop = max(0.0, stop - dividend) if stop is not None else None
        high = max(0.0, high - dividend) if high is not None else None
    if split:
        stop = stop / ratio if stop is not None else None
        high = high / ratio if high is not None else None
    reference = values.previous_close
    if not np.isfinite(ratio) or not np.isfinite(dividend):
        reference = float("nan")
    else:
        if dividend > 0:
            reference = max(reference - dividend, 0.0)
        if split:
            reference /= ratio
    return EventPriceResult(reference, stop, high, split)
