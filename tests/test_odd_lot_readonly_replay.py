"""Read-only authenticated replay can verify a completed prefix but never advance."""
from dataclasses import fields, replace

import pandas as pd
import pytest
from test_odd_lot_durable_replay import _fixture

from quant_fund_lab.odd_lot_paper.replay import _replay_account


def _prefix(data):
    return replace(data,**{field.name:getattr(data,field.name).iloc[:45].copy()
        for field in fields(data) if isinstance(getattr(data,field.name),pd.DataFrame)})


def test_readonly_replay_checks_prefix_and_refuses_new_sessions_without_writes(tmp_path):
    data,research,base,identity = _fixture()
    prefix = _prefix(data)
    path = tmp_path/"account.sqlite"
    first = _replay_account(path,prefix,research,base,identity,create=True)
    before = path.read_bytes()
    checked = _replay_account(path,prefix,research,base,identity,_read_only=True)
    assert checked.checkpoint == first.checkpoint and checked.last_digest == first.last_digest
    assert checked.committed_sessions == 0 and path.read_bytes() == before
    with pytest.raises(ValueError,match="cannot advance"):
        _replay_account(path,data,research,base,identity,_read_only=True)
    assert path.read_bytes() == before


def test_readonly_replay_cannot_create_or_initialize_missing_account(tmp_path):
    data,research,base,identity = _fixture()
    path = tmp_path/"missing.sqlite"
    with pytest.raises(ValueError,match="cannot create"):
        _replay_account(path,data,research,base,identity,create=True,_read_only=True)
    assert not path.exists()
    with pytest.raises(ValueError,match="existing account"):
        _replay_account(path,data,research,base,identity,_read_only=True)
    assert not path.exists()


def test_readonly_replay_rejects_changed_committed_prices(tmp_path):
    data,research,base,identity = _fixture()
    prefix = _prefix(data)
    path = tmp_path/"account.sqlite"
    _replay_account(path,prefix,research,base,identity,create=True)
    before = path.read_bytes()
    opening = prefix.raw_open.copy()
    opening.iloc[40,0] += 1.
    with pytest.raises(ValueError,match="prefix changed"):
        _replay_account(path,replace(prefix,raw_open=opening),research,base,identity,_read_only=True)
    assert path.read_bytes() == before
