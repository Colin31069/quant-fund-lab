"""Historical rebuild requires a verified parent and an unrelated new target path."""
import json
import sqlite3

import pytest
from decision_fixtures import decision_fixture
from test_odd_lot_registered_account import SOURCE

from quant_fund_lab.odd_lot_paper.inspection import inspect_account
from quant_fund_lab.odd_lot_paper.ledger import OddLotLedger
from quant_fund_lab.odd_lot_paper.rebuild import rebuild_registered_account
from quant_fund_lab.odd_lot_paper.workflow import replay_registered_account


def _setup(tmp_path,monkeypatch):
    _,protocol,frozen,_ = decision_fixture(tmp_path,monkeypatch)
    period = next(row for row in protocol.periods if row.name == "validation")
    parent = tmp_path/"parent.sqlite"
    args = {"period":"validation","strategy":"momentum","studies_directory":tmp_path/"studies",
            "source_directory":SOURCE,"snapshot_root":tmp_path/"snapshots","through":period.start}
    original = replay_registered_account(frozen,protocol.candidates[0].candidate_id,
        account_path=parent,create=True,**args)
    return parent,protocol,frozen,args,original


def test_rebuild_keeps_parent_bytes_and_reproduces_business_checkpoint(tmp_path,monkeypatch):
    parent,protocol,frozen,args,original = _setup(tmp_path,monkeypatch)
    before = parent.read_bytes()
    new = tmp_path/"rebuilt.sqlite"
    result = rebuild_registered_account(parent,new,frozen,protocol.candidates[0].candidate_id,**args)
    assert result.replay.checkpoint == original.checkpoint
    assert result.replay.last_digest == original.last_digest
    assert result.parent_completion_digest == original.last_digest
    assert result.source_account == str(parent.resolve()) and result.target_account == str(new.resolve())
    assert parent.read_bytes() == before and inspect_account(new).audit.passed
    repeated = replay_registered_account(frozen,protocol.candidates[0].candidate_id,
        account_path=new,**args)
    assert repeated.committed_sessions == 0 and parent.read_bytes() == before


@pytest.mark.parametrize("case",["same_path","existing_target","different_strategy","different_period"])
def test_unsafe_or_different_rebuild_refuses_without_touching_parent(tmp_path,monkeypatch,case):
    parent,protocol,frozen,args,_ = _setup(tmp_path,monkeypatch)
    before = parent.read_bytes()
    target = parent if case == "same_path" else tmp_path/"new.sqlite"
    target_before = None
    if case == "existing_target":
        target.write_bytes(b"existing evidence")
        target_before = target.read_bytes()
    if case == "different_strategy":
        args = {**args,"strategy":"ensemble"}
    if case == "different_period":
        args = {**args,"period":"development"}
    with pytest.raises(ValueError,match="new target|differ from parent"):
        rebuild_registered_account(parent,target,frozen,protocol.candidates[0].candidate_id,**args)
    assert parent.read_bytes() == before
    if target_before is not None:
        assert target.read_bytes() == target_before
    elif target != parent:
        assert not target.exists()


def test_parent_change_after_new_checkpoint_insertion_rolls_back_day(tmp_path,monkeypatch):
    parent,protocol,frozen,args,_ = _setup(tmp_path,monkeypatch)
    before = parent.read_bytes()
    target = tmp_path/"new.sqlite"
    commit = OddLotLedger.commit
    def interrupted(self,record,*,_fault=None,_validate=None):
        def mutate(stage):
            if stage == "checkpoint":
                parent.write_bytes(before+b"external source modification")
            if _fault is not None:
                _fault(stage)
        return commit(self,record,_fault=mutate,_validate=_validate)
    monkeypatch.setattr(OddLotLedger,"commit",interrupted)
    with pytest.raises(ValueError,match="parent account changed"):
        rebuild_registered_account(parent,target,frozen,protocol.candidates[0].candidate_id,**args)
    with sqlite3.connect(target) as db:
        assert not db.execute("SELECT * FROM session_checkpoints").fetchall()
        assert not db.execute("SELECT * FROM session_events").fetchall()
    parent.write_bytes(before)  # Undo only the external fault injected by this test.
    assert inspect_account(parent).audit.passed


def test_missing_or_unrelated_sqlite_parent_never_initializes_target(tmp_path):
    target = tmp_path/"new.sqlite"
    args = {"period":"validation","strategy":"momentum","studies_directory":tmp_path/"studies",
            "source_directory":SOURCE,"snapshot_root":tmp_path/"snapshots"}
    with pytest.raises(ValueError,match="existing regular"):
        rebuild_registered_account(tmp_path/"missing",target,tmp_path/"protocol","a"*64,**args)
    unrelated = tmp_path/"unrelated.sqlite"
    with sqlite3.connect(unrelated) as db:
        db.execute("CREATE TABLE unrelated(value TEXT)")
    before = unrelated.read_bytes()
    with pytest.raises(sqlite3.Error):
        rebuild_registered_account(unrelated,target,tmp_path/"protocol","a"*64,**args)
    assert unrelated.read_bytes() == before and not target.exists()


def test_missing_parent_snapshot_refuses_rebuild_before_new_account_creation(tmp_path,monkeypatch):
    parent,protocol,frozen,args,_ = _setup(tmp_path,monkeypatch)
    before = parent.read_bytes()
    with sqlite3.connect(parent) as db:
        link = json.loads(db.execute("SELECT payload FROM session_events WHERE category='snapshot'").fetchone()[0])
    (args["snapshot_root"]/link["logical_id"]/"close.parquet").unlink()
    target = tmp_path/"new.sqlite"
    with pytest.raises((ValueError,OSError),match="snapshot"):
        rebuild_registered_account(parent,target,frozen,protocol.candidates[0].candidate_id,**args)
    assert parent.read_bytes() == before and not target.exists()
