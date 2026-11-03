"""Lossless business-event encoding with explicit missing-value and scalar kinds."""
from __future__ import annotations

from datetime import date, datetime
from numbers import Integral, Real

import pandas as pd


def encode_event(value: object) -> object:
    if value is None:
        return ["none"]
    if value is pd.NA:
        return ["pd.NA"]
    if value is pd.NaT:
        return ["NaT"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, Integral):
        return ["int", str(value)]
    if isinstance(value, Real):
        return ["float", float(value).hex()]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return ["timestamp", pd.Timestamp(value).isoformat()]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("business event mapping keys must be strings")
        return ["mapping", [[key, encode_event(item)] for key, item in sorted(value.items())]]
    if isinstance(value, (list, tuple)):
        return ["sequence", [encode_event(item) for item in value]]
    raise TypeError(f"unsupported business event value: {type(value).__name__}")


def decode_event(value: list) -> object:
    kind = value[0]
    if kind in {"none", "pd.NA", "NaT"}:
        return {"none": None, "pd.NA": pd.NA, "NaT": pd.NaT}[kind]
    payload = value[1]
    if kind == "float":
        return float.fromhex(payload)
    if kind == "int":
        return int(payload)
    if kind in {"bool", "str"}:
        return payload
    if kind == "timestamp":
        return pd.Timestamp(payload)
    if kind == "mapping":
        return {key: decode_event(item) for key, item in payload}
    if kind == "sequence":
        return [decode_event(item) for item in payload]
    raise ValueError("unsupported business event scalar kind")
