"""Internal durable replay reproduces whole runs and rejects changed history first."""
import sqlite3
from dataclasses import fields, replace

import pandas as pd
import pytest

from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.odd_lot_paper.replay import ReplayIdentity, _replay_account
from quant_fund_lab.odd_lot_research import OddLotResearchConfig


def _fixture():
    data = synthetic_market_data(("2330.TW", "2317.TW"), periods=65, seed=4)
    research = OddLotResearchConfig(strategy="momentum", momentum_lookback=5)
    base = BacktestConfig(initial_cash=100000, base_currency="TWD", strategy=StrategyConfig(warmup_days=30))
    identity = ReplayIdentity("a" * 64, "fixture-code", "fixture-calendar",
                              str(data.close.index[29].date()))
    return data, research, base, identity


def _rows(path):
    with sqlite3.connect(path) as db:
        return {table: db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in ("account_metadata", "session_checkpoints", "session_events")}


def test_full_vs_split_restart_and_complete_replay_are_identical(tmp_path):
    data, research, base, identity = _fixture()
    full, split = tmp_path / "full.sqlite", tmp_path / "split.sqlite"
    result = _replay_account(full, data, research, base, identity, create=True)
    prefix = replace(data, **{field.name: getattr(data, field.name).iloc[:45].copy()
        for field in fields(data) if isinstance(getattr(data, field.name), pd.DataFrame)})
    _replay_account(split, prefix, research, base, identity, create=True)
    resumed = _replay_account(split, data, research, base, identity)
    assert result.checkpoint == resumed.checkpoint and result.last_digest == resumed.last_digest
    assert _rows(full) == _rows(split)
    before = _rows(split)
    assert _replay_account(split, data, research, base, identity).committed_sessions == 0
    assert _rows(split) == before


def test_fault_rolls_back_day_and_retry_does_not_duplicate_events(tmp_path):
    data, research, base, identity = _fixture()
    path = tmp_path / "failed.sqlite"
    def fail(stage):
        if stage == "events":
            raise RuntimeError("interrupted")
    with pytest.raises(RuntimeError, match="interrupted"):
        _replay_account(path, data, research, base, identity, create=True, _fault=fail)
    assert not _rows(path)["session_checkpoints"] and not _rows(path)["session_events"]
    resumed = _replay_account(path, data, research, base, identity)
    reference = tmp_path / "reference.sqlite"
    whole = _replay_account(reference, data, research, base, identity, create=True)
    assert resumed == whole and _rows(path) == _rows(reference)


def test_changed_completed_inputs_and_settings_reject_without_writes(tmp_path):
    data, research, base, identity = _fixture()
    path = tmp_path / "account.sqlite"
    _replay_account(path, data, research, base, identity, create=True)
    before = _rows(path)
    opening = data.raw_open.copy()
    opening.iloc[40, 0] += .01
    with pytest.raises(ValueError, match="prefix changed"):
        _replay_account(path, replace(data, raw_open=opening), research, base, identity)
    with pytest.raises(ValueError, match="configuration"):
        _replay_account(path, data, replace(research, fill_fraction=.25), base, identity)
    assert _rows(path) == before
