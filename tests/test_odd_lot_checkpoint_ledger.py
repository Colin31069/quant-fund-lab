"""Atomic state/event commits, deterministic replay and immutable account settings."""
from dataclasses import replace

import pytest

from quant_fund_lab.odd_lot_paper.ledger import OddLotLedger, SessionCommit, canonical
from quant_fund_lab.odd_lot_paper.types import OddLotSessionState


def _initial():
    return OddLotSessionState("2024-01-02", "2024-01-02", 0, 1000.)


@pytest.mark.parametrize("stage", ["checkpoint", "events"])
def test_failure_rolls_back_all_business_rows_then_reopen_retry_is_exact(tmp_path, stage):
    path = tmp_path / "ledger.sqlite"
    config = canonical({"protocol": "fixture", "initial_cash": 1000})
    ledger = OddLotLedger(path, config_json=config, initial_state=_initial())
    _, parent = ledger.verify()
    state = replace(_initial(), session="2024-01-03", session_offset=1, cash=900., shares=(("2330.TW", 1),))
    commit = SessionCommit(state, "a" * 64, canonical({"fills": [{"symbol": "2330.TW", "quantity": 1}]}), parent)
    def fail(observed):
        if observed == stage:
            raise RuntimeError("simulated interruption")
    with pytest.raises(RuntimeError, match="interruption"):
        ledger.commit(commit, _fault=fail)
    assert ledger.verify() == (_initial(), parent)
    assert ledger.connection.execute("SELECT count(*) FROM session_events").fetchone()[0] == 0
    ledger.close()
    ledger = OddLotLedger(path, config_json=config)
    identity = ledger.commit(commit)
    assert ledger.commit(commit) == identity
    assert ledger.verify() == (state, identity)
    assert ledger.connection.execute("SELECT count(*) FROM session_events").fetchone()[0] == 1
    with pytest.raises(ValueError, match="changed"):
        ledger.commit(replace(commit, input_fingerprint="b" * 64))
    ledger.close()
    before = path.read_bytes()
    with pytest.raises(ValueError, match="configuration"):
        OddLotLedger(path, config_json=canonical({"protocol": "different"}))
    assert path.read_bytes() == before


def test_corrupt_event_or_broken_chain_refuses_resume_and_never_repairs(tmp_path):
    path = tmp_path / "ledger.sqlite"
    ledger = OddLotLedger(path, config_json="{}", initial_state=_initial())
    _, parent = ledger.verify()
    state = replace(_initial(), session="2024-01-03", session_offset=1)
    ledger.commit(SessionCommit(state, "a" * 64, canonical({"nav": [{"cash": 1000}]}), parent))
    ledger.connection.execute("UPDATE session_events SET payload=?", (canonical({"cash": 999}),))
    with pytest.raises(ValueError, match="digest"):
        ledger.verify()
    ledger.close()
    with pytest.raises(ValueError, match="digest"):
        OddLotLedger(path, config_json="{}")


def test_skipped_offsets_and_wrong_parent_are_rolled_back(tmp_path):
    ledger = OddLotLedger(tmp_path / "ledger.sqlite", config_json="{}", initial_state=_initial())
    _, parent = ledger.verify()
    state = replace(_initial(), session="2024-01-03", session_offset=2)
    with pytest.raises(ValueError, match="boundary"):
        ledger.commit(SessionCommit(state, "a" * 64, "{}", parent))
    assert ledger.verify() == (_initial(), parent)
    with pytest.raises(ValueError, match="prefix"):
        ledger.commit(SessionCommit(replace(state, session_offset=1), "a" * 64, "{}", "b" * 64))
    ledger.close()


def test_existing_account_is_never_overwritten_and_missing_open_does_not_create(tmp_path):
    path = tmp_path / "missing.sqlite"
    with pytest.raises(ValueError, match="existing account"):
        OddLotLedger(path, config_json="{}")
    assert not path.exists()
    ledger = OddLotLedger(path, config_json="{}", initial_state=_initial())
    ledger.close()
    before = path.read_bytes()
    with pytest.raises(ValueError, match="cannot replace"):
        OddLotLedger(path, config_json="{}", initial_state=_initial())
    assert path.read_bytes() == before
