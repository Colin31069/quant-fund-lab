"""Checkpoint contracts retain unfinished obligations and exact numeric state."""
from dataclasses import replace

import pytest

from quant_fund_lab.odd_lot_paper.serialization import decode_state, encode_state
from quant_fund_lab.odd_lot_paper.types import (
    FractionalReceivable,
    OddLotSessionState,
    PendingOrder,
    StopState,
    TradeSettlement,
)


def _state():
    return OddLotSessionState("2024-01-05", "2024-01-02", 3, 12345.678901234567,
        shares=(("2330.TW", 10),), stops=(StopState("2330.TW", 90., 105., .1),),
        pending=(PendingOrder("2330.TW", "SELL", 10, "stop"),),
        receivables=(FractionalReceivable("0050.TW", .25, "2024-01-10", "TWD"),),
        settlements=(TradeSettlement("2024-01-04", "2317.TW", "SELL", -5., 1),
                     TradeSettlement("2024-01-05", "2330.TW", "BUY", 1000., 2)),
        passive_submitted=True)


def test_pending_state_roundtrip_preserves_cash_origin_stops_and_fee_payable():
    original = _state()
    restored = decode_state(encode_state(original))
    assert restored == original
    assert restored.cash.hex() == original.cash.hex()
    assert encode_state(restored) == encode_state(original)
    assert restored.session_offset == 3 and restored.passive_submitted
    assert restored.settlements[0].amount == -5


@pytest.mark.parametrize("changes", [
    {"cash": float("nan")}, {"cash": -1}, {"session_offset": True},
    {"origin_session": "2024-01-08"}, {"passive_submitted": 1},
    {"shares": (("2330.TW", 1), ("2330.TW", 2))},
    {"shares": (("2330.TW", 1.5),)}, {"schema_version": True},
    {"pending": []}, {"stops": ({"symbol": "2330.TW"},)},
    {"shares": (["2330.TW", 10],)}, {"terminated": ("",)},
])
def test_invalid_checkpoint_contracts_are_rejected(changes):
    with pytest.raises((ValueError, TypeError)):
        replace(_state(), **changes)


def test_obligation_dates_are_not_guessed_and_settled_history_is_consistent():
    state = _state()
    with pytest.raises(ValueError, match="future session count"):
        replace(state.settlements[0], remaining_sessions=0)
    with pytest.raises(ValueError, match="timing"):
        replace(state.settlements[0], settled_at="2024-01-05")
    completed = replace(state.settlements[0], settled_at="2024-01-05", remaining_sessions=0)
    assert decode_state(encode_state(replace(state, settlements=(completed,)))).settlements == (completed,)
    future = replace(completed, settled_at="2024-01-08")
    with pytest.raises(ValueError, match="beyond checkpoint"):
        replace(state, settlements=(future,))


def test_duplicate_keys_extra_fields_and_nonfinite_json_cannot_hide_state_changes():
    payload = encode_state(_state())
    with pytest.raises(ValueError, match="duplicate"):
        decode_state(payload[:-1] + ',"cash":0}')
    with pytest.raises(TypeError):
        decode_state(payload[:-1] + ',"unknown":0}')
    with pytest.raises(ValueError):
        decode_state(payload.replace('12345.678901234567', 'Infinity'))
