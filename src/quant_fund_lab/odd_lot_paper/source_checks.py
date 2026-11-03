"""Bind stored valuation/risk/signal evidence to fingerprint-verified market panels."""
from __future__ import annotations

import math

import pandas as pd

from ..data import MarketData
from .event_codec import decode_event, encode_event


def risk_input_evidence(data: MarketData, signal_position: int) -> dict:
    signal, current = data.close.index[signal_position:signal_position+2]
    return {"close":data.raw_close.loc[signal].to_dict(),
            "observed_open":data.raw_open.loc[signal].to_dict(),
            "dividends":data.dividends.loc[current].to_dict(),
            "splits":data.stock_splits.loc[current].to_dict(),
            "terminal_symbols":list(data.terminal_returns.loc[current].dropna().index)}


def validate_source_events(events: dict, data: MarketData, session: str, research: dict) -> None:
    """Reject coherent event edits that disagree with authenticated panel values."""
    stamp = pd.Timestamp(session)
    position = int(data.close.index.get_loc(stamp))
    if position < 1:
        raise ValueError("source validation requires prior signal history")
    expected_risk = encode_event(risk_input_evidence(data, position-1))
    expected_marks = encode_event(data.raw_close.loc[stamp].to_dict())
    if events.get("risk_inputs") != [expected_risk] or events.get("valuation") != [expected_marks]:
        raise ValueError("recorded risk or valuation evidence differs from verified market inputs")
    signal_day = data.close.index[position-1]
    for encoded in events.get("signals", []):
        signal = decode_event(encoded)
        symbol = signal["symbol"]
        if pd.Timestamp(signal["timestamp"]) != signal_day or signal["reason"] not in {"entry", "stop", "model_exit"}:
            raise ValueError("signal date or reason differs from supported close policy")
        if signal["price"] != data.raw_close.at[signal_day, symbol]:
            raise ValueError("decision-time signal price differs from verified close")
        if signal["reason"] == "entry" and research["strategy"] != "equal_weight":
            history = data.close.loc[:signal_day,symbol]
            returns = history.pct_change(fill_method=None).dropna().tail(research["volatility_lookback"])
            if len(returns) != research["volatility_lookback"]:
                raise ValueError("entry lacks required risk observations")
            sigma = float(returns.std(ddof=1))
            distance = min(research["max_stop_distance"], max(research["min_stop_distance"],
                            sigma*research["volatility_multiplier"]))
            expected = signal["price"]*(1-distance)
            if not math.isfinite(sigma) or not math.isclose(signal["stop"], expected, abs_tol=1e-8, rel_tol=1e-12):
                raise ValueError("entry stop differs from independently reconstructed volatility policy")
