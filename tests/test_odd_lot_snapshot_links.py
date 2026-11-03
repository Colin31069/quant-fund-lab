"""Durable snapshot links reject file loss/changes even with no new sessions."""
import json
import sqlite3

import pytest
from test_odd_lot_durable_replay import _fixture

from quant_fund_lab.odd_lot_paper.replay import _replay_account
from quant_fund_lab.odd_lot_paper.snapshots import publish_snapshot, verify_snapshot_link


def test_snapshot_publication_retries_preserve_bytes_and_link_is_verified(tmp_path):
    data, _, _, _ = _fixture()
    root = tmp_path / "snapshots"
    link = publish_snapshot(data, root)
    target = root / link["logical_id"]
    before = {p.name:p.read_bytes() for p in target.iterdir()}
    assert publish_snapshot(data, root) == link
    restored = verify_snapshot_link(root, link)
    assert restored.close.equals(data.close)
    assert before == {p.name:p.read_bytes() for p in target.iterdir()}


@pytest.mark.parametrize("change", ["delete", "payload", "manifest"])
def test_committed_snapshot_corruption_blocks_noop_resume_without_ledger_writes(tmp_path, change):
    data, research, base, identity = _fixture()
    path, root = tmp_path / "account.sqlite", tmp_path / "snapshots"
    # One executed day keeps the test focused on preflight, not repeated decoding.
    identity = type(identity)(identity.protocol_id, identity.execution_revision,
                              identity.calendar_revision, str(data.close.index[-2].date()))
    _replay_account(path, data, research, base, identity, create=True, snapshot_root=root)
    with sqlite3.connect(path) as db:
        link = json.loads(db.execute("SELECT payload FROM session_events WHERE category='snapshot'").fetchone()[0])
    target = root / link["logical_id"]
    if change == "delete":
        (target / "close.parquet").unlink()
    elif change == "payload":
        with (target / "close.parquet").open("ab") as file:
            file.write(b"changed")
    else:
        (target / "manifest.json").write_text("{}")
    before = path.read_bytes()
    with pytest.raises((ValueError, OSError), match="snapshot"):
        _replay_account(path, data, research, base, identity, snapshot_root=root)
    assert path.read_bytes() == before


def test_snapshot_root_change_is_a_locked_account_setting(tmp_path):
    data, research, base, identity = _fixture()
    identity = type(identity)(identity.protocol_id, identity.execution_revision,
                              identity.calendar_revision, str(data.close.index[-2].date()))
    path = tmp_path / "account.sqlite"
    _replay_account(path, data, research, base, identity, create=True, snapshot_root=tmp_path / "one")
    with pytest.raises(ValueError, match="configuration"):
        _replay_account(path, data, research, base, identity, snapshot_root=tmp_path / "two")


def test_input_mutation_after_event_insertion_rolls_back_transaction(tmp_path):
    data, research, base, identity = _fixture()
    path = tmp_path / "account.sqlite"
    def mutate(stage):
        if stage == "events":
            data.raw_open.iloc[30, 0] += 1
    with pytest.raises(ValueError, match="changed during"):
        _replay_account(path, data, research, base, identity, create=True, _fault=mutate)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM session_checkpoints").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM session_events").fetchone()[0] == 0
