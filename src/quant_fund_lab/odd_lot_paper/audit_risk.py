"""Independent stop/pending lifecycle reconstruction from close inputs and events."""
from __future__ import annotations

import math
from dataclasses import asdict

from .types import OddLotSessionState


def reconcile_risk_state(previous: OddLotSessionState, current: OddLotSessionState,
                         groups: dict[str, list], research: dict) -> tuple[str, ...]:
    """Check lifecycle algebra without calling signal, matching or session functions.

    Model scores/target weights remain declared signal evidence, not independently
    recomputed alpha. Input provenance is authenticated separately by snapshots.
    """
    rows = groups.get("risk_inputs", [])
    if len(rows) != 1:
        return ("missing unique risk input evidence",)
    inputs = rows[0]
    issues = []
    stops = {row.symbol: asdict(row) for row in previous.stops}
    pending = {row.symbol: asdict(row) for row in previous.pending}
    shares = dict(previous.shares)
    signals = groups.get("signals", [])
    triggered = set()
    for symbol, stop in stops.items():
        price = inputs["close"][symbol]
        opening = inputs["observed_open"][symbol]
        if not math.isfinite(opening) or not math.isfinite(price) or price <= 0:
            continue
        if price <= stop["stop"]:
            triggered.add(symbol)
            pending[symbol] = {"symbol":symbol,"side":"SELL","quantity":shares[symbol],
                "reason":"stop","stop":0.,"signal_price":0.,"distance":0.,"signal_volume":0.}
        else:
            stop["high_close"] = max(stop["high_close"], price)
            stop["stop"] = max(stop["stop"], stop["high_close"]*(1-stop["distance"]))
    reported_stops = [row["symbol"] for row in signals if row["reason"] == "stop"]
    if set(reported_stops) != triggered or len(reported_stops) != len(triggered):
        issues.append("stop signals differ from independently triggered stops")
    entries = {}
    for signal in signals:
        symbol = signal["symbol"]
        if signal["reason"] == "entry":
            entries[symbol] = signal
        elif signal["reason"] == "model_exit":
            if symbol in triggered or not shares.get(symbol, 0):
                issues.append("model exit overrides stop or lacks held position")
            pending[symbol] = {"symbol":symbol,"side":"SELL","quantity":shares.get(symbol, 0),
                "reason":"model_exit","stop":0.,"signal_price":0.,"distance":0.,"signal_volume":0.}
    for symbol, stop in stops.items():
        dividend, ratio = inputs["dividends"][symbol], inputs["splits"][symbol]
        if math.isfinite(dividend) and dividend > 0:
            stop["stop"] = max(0., stop["stop"]-dividend)
            stop["high_close"] = max(0., stop["high_close"]-dividend)
        if math.isfinite(ratio) and ratio > 0 and not math.isclose(ratio, 1., rel_tol=1e-5, abs_tol=1e-8):
            stop["stop"] /= ratio
            stop["high_close"] /= ratio
    terminated = set(previous.terminated) | set(inputs["terminal_symbols"])
    removed = set(inputs["terminal_symbols"]) | {row["symbol"] for row in groups.get("actions", [])
        if row["action"] == "stock_split" and row["quantity_after"] == 0}
    for symbol in removed:
        stops.pop(symbol, None)
        pending.pop(symbol, None)
    final_shares = dict(current.shares)
    for fill in groups.get("fills", []):
        symbol = fill["symbol"]
        if fill["side"] == "BUY" and research["strategy"] != "equal_weight":
            signal = entries.get(symbol)
            if signal is None or signal["price"] <= 0:
                issues.append("entry fill lacks a valid decision-time signal")
                continue
            stops[symbol] = {"symbol":symbol,"stop":signal["stop"],"high_close":signal["price"],
                             "distance":1-signal["stop"]/signal["price"]}
            if fill["entry_risk_budget"] != research["risk_budget"]:
                issues.append("entry risk budget differs from frozen policy")
        elif fill["side"] == "SELL" and final_shares.get(symbol, 0) <= 0:
            stops.pop(symbol, None)
            pending.pop(symbol, None)
    pending = {symbol:row for symbol,row in pending.items() if row["side"] == "SELL"}
    actual = {row.symbol:asdict(row) for row in current.stops}
    if set(stops) != set(actual):
        issues.append("checkpoint stop symbols differ")
    else:
        for symbol, expected in stops.items():
            for key in ("stop", "high_close", "distance"):
                if not math.isclose(actual[symbol][key], expected[key], abs_tol=1e-8, rel_tol=1e-12):
                    issues.append("checkpoint stop "+key+" differs")
    if pending != {row.symbol:asdict(row) for row in current.pending}:
        issues.append("checkpoint pending orders differ")
    if terminated != set(current.terminated):
        issues.append("checkpoint terminal state differs")
    submitted = previous.passive_submitted or previous.session_offset % research["rebalance_every"] == 0
    if current.passive_submitted != submitted:
        issues.append("checkpoint first-entry flag differs")
    return tuple(issues)
