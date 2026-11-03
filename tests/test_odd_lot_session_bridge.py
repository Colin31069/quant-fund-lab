"""Historical checkpoints rebase indexes without changing unresolved obligations."""
from dataclasses import replace

import pytest
from test_odd_lot_session_state import _state

from quant_fund_lab.odd_lot_paper.bridge import capture_session_state, restore_session_state


def test_checkpoint_rebase_preserves_pending_obligations_and_does_not_alias_state():
    checkpoint = _state()
    runtime = restore_session_state(checkpoint, completed_index=120)
    assert [row["due_session_index"] for row in runtime.settlements] == [121, 122]
    restored = capture_session_state(runtime, session=checkpoint.session,
        origin_session=checkpoint.origin_session, session_offset=3, completed_index=120)
    assert restored == checkpoint
    rebased = restore_session_state(restored, completed_index=5)
    assert [row["due_session_index"] for row in rebased.settlements] == [6, 7]
    runtime.portfolio.cash = 0
    runtime.stops["2330.TW"].stop = 1
    runtime.pending.clear()
    assert rebased.portfolio.cash == checkpoint.cash
    assert rebased.stops["2330.TW"].stop == 90
    assert rebased.pending and checkpoint.pending


def test_settled_history_roundtrip_and_stale_unsettled_obligations_reject():
    checkpoint = _state()
    settled = replace(checkpoint.settlements[0], remaining_sessions=0, settled_at="2024-01-05")
    checkpoint = replace(checkpoint, settlements=(settled, checkpoint.settlements[1]))
    runtime = restore_session_state(checkpoint, completed_index=3)
    assert capture_session_state(runtime, session=checkpoint.session,
        origin_session=checkpoint.origin_session, session_offset=3, completed_index=3) == checkpoint
    runtime.settlements[1]["due_session_index"] = 3
    with pytest.raises(ValueError, match="future session count"):
        capture_session_state(runtime, session=checkpoint.session,
            origin_session=checkpoint.origin_session, session_offset=3, completed_index=3)


@pytest.mark.parametrize("index", [-1, True, 1.5])
def test_invalid_global_indexes_are_rejected(index):
    with pytest.raises(ValueError, match="completed index"):
        restore_session_state(_state(), completed_index=index)
