"""Event storage retains missing kinds and exact floating-point business values."""
import math

import pandas as pd
import pytest

from quant_fund_lab.odd_lot_paper.event_codec import decode_event, encode_event
from quant_fund_lab.odd_lot_paper.ledger import canonical


def test_exact_event_roundtrip_preserves_numbers_dates_and_missing_kinds():
    value = {"quantity": 10, "price": 123.45678901234567, "score": float("nan"),
             "timestamp": pd.Timestamp("2024-01-05"), "none": None,
             "unknown": pd.NA, "date_unknown": pd.NaT, "flag": True}
    encoded = encode_event(value)
    assert "NaN" not in canonical(encoded)
    restored = decode_event(encoded)
    assert restored["price"].hex() == value["price"].hex()
    assert type(restored["quantity"]) is int and restored["quantity"] == 10
    assert math.isnan(restored["score"]) and restored["timestamp"] == value["timestamp"]
    assert restored["unknown"] is pd.NA and restored["date_unknown"] is pd.NaT
    assert restored["none"] is None and restored["flag"] is True
    assert encode_event(restored) == encoded


def test_unsupported_scalars_and_ambiguous_mapping_keys_are_rejected():
    with pytest.raises(TypeError):
        encode_event({1: "integer key", "1": "string key"})
    with pytest.raises(TypeError):
        encode_event(object())
    with pytest.raises(ValueError, match="scalar kind"):
        decode_event(["unknown", 1])
