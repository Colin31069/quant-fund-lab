"""Canonical state encoding without float rounding, timestamps or mutable aliases."""
import json

from .types import (
    FractionalReceivable,
    OddLotSessionState,
    PendingOrder,
    StopState,
    TradeSettlement,
)


def encode_state(state: OddLotSessionState) -> str:
    return json.dumps(state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)


def decode_state(payload: str) -> OddLotSessionState:
    def unique_pairs(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise ValueError("duplicate state JSON key")
            values[key] = value
        return values

    values = json.loads(payload, object_pairs_hook=unique_pairs)
    if not isinstance(values, dict):
        raise TypeError("state must be a JSON object")
    for name, cls in (("stops", StopState), ("pending", PendingOrder),
                      ("receivables", FractionalReceivable), ("settlements", TradeSettlement)):
        values[name] = tuple(cls(**row) for row in values[name])
    values["shares"] = tuple(tuple(row) for row in values["shares"])
    values["terminated"] = tuple(values["terminated"])
    return OddLotSessionState(**values)
