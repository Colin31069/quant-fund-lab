"""Stop lifecycle equations and rehashed risk-state changes are independently checked."""
import json
import sqlite3
from dataclasses import replace

import pytest
from test_odd_lot_accounting_audit import _rehash_latest
from test_odd_lot_durable_replay import _fixture

from quant_fund_lab.odd_lot_paper.audit import audit_accounting
from quant_fund_lab.odd_lot_paper.audit_risk import reconcile_risk_state
from quant_fund_lab.odd_lot_paper.ledger import canonical
from quant_fund_lab.odd_lot_paper.replay import _replay_account
from quant_fund_lab.odd_lot_paper.types import OddLotSessionState, PendingOrder, StopState


def test_trailing_dividend_then_split_levels_are_independently_reconstructed():
    previous = OddLotSessionState("2024-01-04", "2024-01-02", 2, 0.,
        shares=(("2330.TW",10),),stops=(StopState("2330.TW",95.,100.,.1),),passive_submitted=True)
    current = replace(previous,session="2024-01-05",session_offset=3,
        shares=(("2330.TW",20),),stops=(StopState("2330.TW",48.5,54.,.1),))
    groups = {"risk_inputs":[{"close":{"2330.TW":110.},"observed_open":{"2330.TW":110.},
        "dividends":{"2330.TW":2.},"splits":{"2330.TW":2.},"terminal_symbols":[]}]}
    policy = {"rebalance_every":5,"strategy":"momentum","risk_budget":2000}
    assert not reconcile_risk_state(previous,current,groups,policy)
    wrong = replace(current,stops=(StopState("2330.TW",49.,54.,.1),))
    assert any("stop" in issue for issue in reconcile_risk_state(previous,wrong,groups,policy))


def test_stop_trigger_retains_sell_retry_and_does_not_disappear_without_fill():
    previous = OddLotSessionState("2024-01-04", "2024-01-02", 2, 0.,
        shares=(("2330.TW",10),),stops=(StopState("2330.TW",95.,100.,.1),),passive_submitted=True)
    current = replace(previous,session="2024-01-05",session_offset=3,
        pending=(PendingOrder("2330.TW","SELL",10,"stop"),))
    groups = {"risk_inputs":[{"close":{"2330.TW":90.},"observed_open":{"2330.TW":90.},
        "dividends":{"2330.TW":0.},"splits":{"2330.TW":1.},"terminal_symbols":[]}],
        "signals":[{"symbol":"2330.TW","reason":"stop"}]}
    policy = {"rebalance_every":5,"strategy":"momentum","risk_budget":2000}
    assert not reconcile_risk_state(previous,current,groups,policy)
    assert any("pending" in issue for issue in reconcile_risk_state(previous,replace(current,pending=()),groups,policy))


@pytest.mark.parametrize("field", ["stops", "pending", "passive_submitted"])
def test_rehashed_checkpoint_risk_mutation_blocks_resume(tmp_path, field):
    path = tmp_path / "account.sqlite"
    data,research,base,identity = _fixture()
    _replay_account(path,data,research,base,identity,create=True)
    with sqlite3.connect(path) as db:
        session,payload = db.execute("SELECT session,state_json FROM session_checkpoints ORDER BY session DESC LIMIT 1").fetchone()
        state = json.loads(payload)
        if field == "passive_submitted":
            state[field] = not state[field]
        elif field == "stops":
            state[field] = [{"symbol":"ghost.TW","stop":90.,"high_close":100.,"distance":.1}]
        else:
            state[field] = [{"symbol":"ghost.TW","side":"SELL","quantity":1,"reason":"stop",
                             "stop":0.,"signal_price":0.,"distance":0.,"signal_volume":0.}]
        db.execute("UPDATE session_checkpoints SET state_json=? WHERE session=?",(canonical(state),session))
        _rehash_latest(db,session)
    assert not audit_accounting(path).passed
    with pytest.raises(ValueError,match="independent accounting"):
        _replay_account(path,data,research,base,identity)
