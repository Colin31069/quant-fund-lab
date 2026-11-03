"""Public day workflow commits/restarts receipt lifecycle and detects rehashed NAV."""
import json
from dataclasses import replace
from decimal import Decimal

import pytest
from rights_durable_day_fixtures import initial_day, next_day

from quant_fund_lab.odd_lot_rights.codec import canonical
from quant_fund_lab.odd_lot_rights.durable_day_audit import verify_durable_days
from quant_fund_lab.odd_lot_rights.durable_day_workflow import commit_rights_day
from quant_fund_lab.odd_lot_rights.engine_ledger import RightsEngineLedger
from quant_fund_lab.odd_lot_rights.engine_ledger_types import payload_digest


@pytest.mark.parametrize("restart", [False, True])
def test_receipt_delivery_partial_sale_conversion_and_unlock_commit_from_reopened_checkpoint(tmp_path, monkeypatch, restart):
    context, initial, config, day = initial_day(monkeypatch)
    path = tmp_path/"workflow.sqlite"
    ledger = RightsEngineLedger(path, config=config, initial=initial)
    days, cash, nav = [], [], []
    for index in range(29, 36):
        if index > 29:
            day = next_day(context, ledger.verify()[0], index)
        committed = commit_rights_day(ledger, day)
        days.append(day)
        cash.append(committed.commit.checkpoint.engine.cash)
        nav.append(committed.nav.nav)
        assert ledger.verify()[1] == committed.digest
        if restart:
            ledger.close()
            ledger = RightsEngineLedger(path, config=config)
    assert cash == [50., 50., 50., 250., 250., 550., 550.]
    assert nav == [1050]*7
    assert verify_durable_days(ledger, tuple(days)).sessions_checked == 7
    ledger.close()
    before = path.read_bytes()
    read = RightsEngineLedger(path, config=config, read_only=True)
    assert verify_durable_days(read, tuple(days)).sessions_checked == 7
    read.close()
    assert path.read_bytes() == before


@pytest.mark.parametrize("phase", ["checkpoint", "events", "completion", "before_commit"])
@pytest.mark.parametrize("error", [RuntimeError, KeyboardInterrupt])
def test_day_failure_rolls_back_delivery_original_authorization_risk_and_nav(tmp_path, monkeypatch, phase, error):
    _, initial, config, day = initial_day(monkeypatch)
    path = tmp_path/"fault.sqlite"
    ledger = RightsEngineLedger(path, config=config, initial=initial)
    original = ledger.verify()

    def fault(where):
        if where == phase:
            raise error("interrupted day")

    with pytest.raises(error):
        commit_rights_day(ledger, day, _fault=fault)
    assert ledger.verify() == original
    ledger.close()
    reopened = RightsEngineLedger(path, config=config)
    done = commit_rights_day(reopened, day)
    assert done.commit.checkpoint.engine.cash == 50.
    assert len(done.commit.checkpoint.account.authorizations) == 1
    assert sum(row.units for row in done.commit.checkpoint.account.inventory.lots) == 10
    assert verify_durable_days(reopened, (day,)).sessions_checked == 1
    reopened.close()


@pytest.mark.parametrize("change", ["settings", "prior_risk", "mark", "source", "missing_day"])
def test_original_request_replay_rejects_changed_source_settings_or_risk(tmp_path, monkeypatch, change):
    _, initial, config, day = initial_day(monkeypatch)
    ledger = RightsEngineLedger(tmp_path/"input.sqlite", config=config, initial=initial)
    commit_rights_day(ledger, day)
    days = (day,)
    if change == "settings":
        inputs = replace(day.request.inputs, research=replace(day.request.inputs.research, risk_budget=999.))
        days = (replace(day, request=replace(day.request, inputs=inputs)),)
    elif change == "prior_risk":
        from copy import deepcopy

        runtime = deepcopy(day.request.inputs.runtime)
        runtime.stops["PARENT.TW"].stop = 94.
        days = (replace(day, request=replace(day.request, inputs=replace(day.request.inputs, runtime=runtime))),)
    elif change == "mark":
        days = (replace(day, securities=(replace(day.securities[0], unit_value=Decimal(99)), *day.securities[1:])),)
    elif change == "source":
        frame = day.request.inputs.data.volume.copy()
        frame.iloc[0, 0] += 1
        inputs = replace(day.request.inputs, data=replace(day.request.inputs.data, volume=frame))
        days = (replace(day, request=replace(day.request, inputs=inputs)),)
    else:
        days = ()
    before = ledger.verify()
    with pytest.raises((ValueError, TypeError)):
        verify_durable_days(ledger, days)
    assert ledger.verify() == before
    ledger.close()


def test_rehashed_sql_nav_is_rejected_by_external_request_reconstruction(tmp_path, monkeypatch):
    _, initial, config, day = initial_day(monkeypatch)
    ledger = RightsEngineLedger(tmp_path/"nav.sqlite", config=config, initial=initial)
    commit_rights_day(ledger, day)
    session, state, inputs, parent = ledger.connection.execute(
        "SELECT session,state_json,input_digest,parent_digest FROM rights_checkpoints").fetchone()
    events = json.loads(ledger.connection.execute("SELECT events_json FROM rights_events").fetchone()[0])
    events["rights_nav"][0]["nav"] = "999999"
    payload = canonical(events)
    ledger.connection.execute("UPDATE rights_events SET events_json=? WHERE session=?", (payload, session))
    digest = payload_digest(canonical([parent, state, inputs, payload]))
    ledger.connection.execute("UPDATE rights_completed SET commit_digest=? WHERE session=?", (digest, session))
    assert ledger.verify()[1] == digest  # Storage integrity alone cannot certify NAV.
    with pytest.raises(ValueError, match="original-request replay"):
        verify_durable_days(ledger, (day,))
    ledger.close()


@pytest.mark.parametrize("phase", ["checkpoint", "before_commit"])
def test_mutated_source_during_commit_is_rejected_and_whole_day_rolls_back(tmp_path, monkeypatch, phase):
    _, initial, config, day = initial_day(monkeypatch)
    ledger = RightsEngineLedger(tmp_path/"race.sqlite", config=config, initial=initial)
    before = ledger.verify()

    def mutate(where):
        if where == phase:
            day.request.inputs.data.volume.iloc[0, 0] += 1

    with pytest.raises(ValueError, match="inputs changed before commit"):
        commit_rights_day(ledger, day, _fault=mutate)
    assert ledger.verify() == before
    assert ledger.connection.execute("SELECT COUNT(*) FROM rights_completed").fetchone()[0] == 0
    ledger.close()
