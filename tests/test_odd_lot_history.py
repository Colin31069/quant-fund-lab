"""Incremental bars use verified old snapshots and cannot replace completed values."""
from dataclasses import fields, replace

import pandas as pd
import pytest
from test_odd_lot_durable_replay import _fixture

from quant_fund_lab.odd_lot_paper.history import reconstruct_account_history
from quant_fund_lab.odd_lot_paper.replay import _replay_account


def _slice(data, start, stop):
    return replace(data, **{field.name:getattr(data, field.name).iloc[start:stop].copy()
        for field in fields(data) if isinstance(getattr(data, field.name), pd.DataFrame)})


def test_delta_reconstructs_completed_prefix_and_resumes_same_as_full_input(tmp_path):
    data, research, base, identity = _fixture()
    path, snapshots = tmp_path / "account.sqlite", tmp_path / "snapshots"
    _replay_account(path, _slice(data, 0, 32), research, base, identity, create=True, snapshot_root=snapshots)
    before = path.read_bytes()
    rebuilt = reconstruct_account_history(path, snapshots, _slice(data, 32, 34))
    assert path.read_bytes() == before
    expected = _slice(data, 0, 34)
    # Parquet retains exact dates/values, not pandas' optional frequency hint.
    pd.testing.assert_frame_equal(rebuilt.raw_close, expected.raw_close, check_freq=False)
    resumed = _replay_account(path, rebuilt, research, base, identity, snapshot_root=snapshots)
    reference = _replay_account(tmp_path / "whole.sqlite", expected, research, base, identity,
                                create=True, snapshot_root=tmp_path / "whole_snapshots")
    assert resumed.checkpoint == reference.checkpoint
    overlapping = _slice(data, 30, 34)
    changed = overlapping.raw_open.copy()
    changed.iloc[0,0] += 1
    with pytest.raises(ValueError, match="overlap"):
        reconstruct_account_history(path, snapshots, replace(overlapping, raw_open=changed))
