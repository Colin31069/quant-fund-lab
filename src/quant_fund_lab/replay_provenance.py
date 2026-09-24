"""Canonical, per-session replay input provenance independent of Parquet bytes."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime

import numpy as np
import pandas as pd

from .data import MarketData

_REPLAY_INPUT_FIELDS = (
    "open",
    "close",
    "volume",
    "raw_open",
    "raw_close",
    "reference",
    "membership",
    "terminal_returns",
    "dividends",
    "stock_splits",
    "cash_in_lieu_prices",
    "cash_in_lieu_settlement_dates",
    "fx_to_base",
    "fx_age_days",
    "market_codes",
    "currency_codes",
)


def _canonical_cell(value: object) -> object:
    """Encode scalar values with explicit float bits and unambiguous nulls."""

    if value is None or bool(pd.isna(value)):
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64, datetime, date)):
        return {"timestamp": pd.Timestamp(value).isoformat()}
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("replay input provenance cannot encode nonfinite market values")
        return {"float64": value.hex()}
    raise TypeError(f"unsupported replay input provenance scalar: {type(value).__name__}")


def replay_session_data_fingerprint(
    data: MarketData,
    timestamp: pd.Timestamp,
    execution_reference: pd.Series,
    benchmark_close_base: float | None,
) -> str:
    """SHA-256 of all model-visible market inputs for one committed session.

    The schema includes raw/adjusted prices, FX, lifecycle, settlement metadata,
    the transition-safe execution reference and the benchmark mark. It also
    distinguishes missing frames from all-null frames and preserves symbol order.
    """

    stamp = pd.Timestamp(timestamp)
    symbols = data.symbols
    frames: dict[str, object] = {}
    for name in _REPLAY_INPUT_FIELDS:
        frame = getattr(data, name)
        if frame is None:
            frames[name] = None
            continue
        row = frame.loc[stamp]
        frames[name] = [_canonical_cell(row[symbol]) for symbol in symbols]

    payload = {
        "schema_version": 1,
        "timestamp": stamp.isoformat(),
        "symbols": symbols,
        "exchange": data.exchange,
        "base_currency": data.base_currency,
        "frames": frames,
        "effective_execution_reference": [
            _canonical_cell(execution_reference[symbol]) for symbol in symbols
        ],
        "benchmark_close_base": _canonical_cell(benchmark_close_base),
    }
    canonical_json = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
