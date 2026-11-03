"""Each completed-input or locked-setting mutation is rejected before account writes."""
import sqlite3
from dataclasses import replace

import pandas as pd
import pytest
from test_odd_lot_accounting_audit import _rehash_latest
from test_odd_lot_durable_replay import _fixture

from quant_fund_lab.odd_lot_paper.audit import audit_accounting
from quant_fund_lab.odd_lot_paper.ledger import OddLotLedger, canonical
from quant_fund_lab.odd_lot_paper.replay import _replay_account
from quant_fund_lab.odd_lot_paper.snapshots import publish_snapshot, verify_snapshot_link


def _completed_account(tmp_path):
    data, research, base, identity = _fixture()
    # One real completed transition; its full prior warmup remains part of the locked prefix.
    identity = replace(identity, origin_session=str(data.close.index[-2].date()))
    path = tmp_path / "account.sqlite"
    first = _replay_account(path, data, research, base, identity, create=True)
    assert first.committed_sessions == 1
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    return path, data, research, base, identity, before


@pytest.mark.parametrize("field", ["raw_open", "raw_close", "close", "volume", "dividends", "stock_splits"])
@pytest.mark.parametrize("position", [40, 64])
def test_changed_warmup_or_completed_day_refuses_even_without_new_sessions(tmp_path, field, position):
    path, data, research, base, identity, before = _completed_account(tmp_path)
    frame = getattr(data, field).copy(deep=True)
    if field == "stock_splits":
        frame.iloc[position, 0] = 2
    else:
        frame.iloc[position, 0] += 1
    incoming = replace(data, **{field: frame})
    with pytest.raises(ValueError):
        _replay_account(path, incoming, research, base, identity)
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("case", ["commission", "slippage", "fill_fraction", "risk_budget",
    "rebalance", "tax", "interest", "calendar", "protocol", "execution"])
def test_every_locked_execution_or_identity_change_refuses_without_reset(tmp_path, case):
    path, data, research, base, identity, before = _completed_account(tmp_path)
    if case == "commission":
        research = replace(research, min_commission=research.min_commission + 1)
    elif case == "slippage":
        research = replace(research, slippage_bps=research.slippage_bps + 1)
    elif case == "fill_fraction":
        research = replace(research, fill_fraction=.25)
    elif case == "risk_budget":
        research = replace(research, risk_budget=research.risk_budget + 1)
    elif case == "rebalance":
        research = replace(research, rebalance_every=research.rebalance_every + 1)
    elif case == "tax":
        rules = {symbol: {**rule, "sell_tax_bps": rule["sell_tax_bps"] + 1}
                 for symbol, rule in research.instrument_rules.items()}
        research = replace(research, instrument_rules=rules)
    elif case == "interest":
        base = replace(base, cash_annual_yield=.01)
    elif case == "calendar":
        identity = replace(identity, calendar_revision="changed-calendar")
    elif case == "protocol":
        identity = replace(identity, protocol_id="b" * 64)
    else:
        identity = replace(identity, execution_revision="changed-code")
    with pytest.raises(ValueError, match="configuration"):
        _replay_account(path, data, research, base, identity)
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}



def test_rehashed_sql_link_to_another_valid_snapshot_still_rejects_resume(tmp_path):
    data, research, base, identity = _fixture()
    identity = replace(identity, origin_session=str(data.close.index[-2].date()))
    path, snapshots = tmp_path / "account.sqlite", tmp_path / "snapshots"
    _replay_account(path, data, research, base, identity, create=True, snapshot_root=snapshots)
    opening = data.raw_open.copy(deep=True)
    opening.iloc[40, 0] += .01
    alternative = replace(data, raw_open=opening)
    link = publish_snapshot(alternative, snapshots)
    assert verify_snapshot_link(snapshots, link).raw_open.equals(opening)
    with sqlite3.connect(path) as db:
        session = db.execute("SELECT max(session) FROM session_checkpoints").fetchone()[0]
        db.execute("UPDATE session_events SET payload=? WHERE session=? AND category='snapshot'",
                   (canonical(link), session))
        _rehash_latest(db, session)
        config = db.execute("SELECT value FROM account_metadata WHERE key='config'").fetchone()[0]
    ledger = OddLotLedger(path, config_json=config, read_only=True)
    try:
        ledger.verify()
    finally:
        ledger.close()
    # Both the normalized snapshot and account hash chain are valid. Financial
    # equations cannot detect this alternative warmup input; provenance must.
    assert audit_accounting(path).passed
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="snapshot input prefix differs"):
        _replay_account(path, data, research, base, identity, snapshot_root=snapshots)
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}



def test_nonzero_interest_accrues_once_across_restart_and_completed_noop(tmp_path, monkeypatch):
    data, research, base, identity = _fixture()
    origin = data.close.index[-4]
    identity = replace(identity, origin_session=str(origin.date()))
    base = replace(base, cash_annual_yield=.0365)

    def no_entries(history, *_args):
        return pd.Series(0.0, index=history.columns), pd.Series(0.0, index=history.columns)

    monkeypatch.setattr("quant_fund_lab.odd_lot_research._targets", no_entries)
    full, split = tmp_path / "full.sqlite", tmp_path / "split.sqlite"
    whole = _replay_account(full, data, research, base, identity, create=True)
    prefix = data.slice(end=data.close.index[-3])
    partial = _replay_account(split, prefix, research, base, identity, create=True)
    continued = _replay_account(split, data, research, base, identity)
    assert partial.committed_sessions == 1 and continued.committed_sessions == 2
    assert whole.checkpoint == continued.checkpoint and whole.last_digest == continued.last_digest
    expected, previous = 100000.0, origin
    for date in data.close.index[-3:]:
        expected += expected * .0365 * (date - previous).days / 365
        previous = date
    assert expected > 100000 and continued.checkpoint.cash == pytest.approx(expected)
    assert not continued.checkpoint.shares and audit_accounting(split).passed
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = _replay_account(split, data, research, base, identity)
    assert result.committed_sessions == 0 and result.checkpoint.cash == continued.checkpoint.cash
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
