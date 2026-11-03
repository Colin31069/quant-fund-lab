"""Stored event sources must match actual panels even after rehashing the account."""
import json
import sqlite3
from dataclasses import asdict

import pytest
from test_odd_lot_accounting_audit import _rehash_latest
from test_odd_lot_durable_replay import _fixture

from quant_fund_lab.odd_lot_paper.audit import audit_accounting
from quant_fund_lab.odd_lot_paper.event_codec import decode_event, encode_event
from quant_fund_lab.odd_lot_paper.ledger import canonical
from quant_fund_lab.odd_lot_paper.replay import _replay_account
from quant_fund_lab.odd_lot_paper.source_checks import risk_input_evidence, validate_source_events


def test_coherent_risk_input_edit_cannot_be_certified_only_by_account_internal_audit(tmp_path):
    data,research,base,identity = _fixture()
    path = tmp_path / "account.sqlite"
    _replay_account(path,data,research,base,identity,create=True)
    with sqlite3.connect(path) as db:
        session = db.execute("SELECT max(session) FROM session_checkpoints").fetchone()[0]
        payload = db.execute("SELECT payload FROM session_events WHERE session=? AND category='risk_inputs'",(session,)).fetchone()[0]
        evidence = decode_event(json.loads(payload))
        evidence["observed_open"][data.symbols[0]] += .01
        db.execute("UPDATE session_events SET payload=? WHERE session=? AND category='risk_inputs'",
                   (canonical(encode_event(evidence)),session))
        _rehash_latest(db,session)
    # The changed finite open leaves all accounting and risk equations unchanged.
    assert audit_accounting(path).passed
    before = path.read_bytes()
    with pytest.raises(ValueError,match="differs from verified market"):
        _replay_account(path,data,research,base,identity)
    assert path.read_bytes() == before


def test_signal_entry_stop_is_independently_bound_to_history_volatility():
    data,research,_,_ = _fixture()
    position = 40
    day = data.close.index[position]
    symbol = data.symbols[0]
    signal_day = data.close.index[position-1]
    price = data.raw_close.at[signal_day,symbol]
    returns = data.close.loc[:signal_day,symbol].pct_change(fill_method=None).dropna().tail(research.volatility_lookback)
    distance = min(research.max_stop_distance,max(research.min_stop_distance,
                   returns.std(ddof=1)*research.volatility_multiplier))
    signal = {"timestamp":signal_day,"symbol":symbol,"reason":"entry","price":price,"stop":price*(1-distance)}
    groups = {"risk_inputs":[encode_event(risk_input_evidence(data,position-1))],
              "valuation":[encode_event(data.raw_close.loc[day].to_dict())],
              "signals":[encode_event(signal)]}
    validate_source_events(groups,data,day.date().isoformat(),asdict(research))
    groups["signals"] = [encode_event({**signal,"stop":signal["stop"]+1})]
    with pytest.raises(ValueError,match="volatility policy"):
        validate_source_events(groups,data,day.date().isoformat(),asdict(research))
