"""Close planning keeps risk precedence, origin and history-cutoff contracts."""
from dataclasses import replace

import pandas as pd
import pytest

from quant_fund_lab.config import BacktestConfig
from quant_fund_lab.execution import PortfolioState
from quant_fund_lab.odd_lot_paper.engine_records import EngineStop
from quant_fund_lab.odd_lot_paper.signals import SignalPlanInput, plan_close_signals
from quant_fund_lab.odd_lot_research import OddLotResearchConfig


def _inputs():
    day = pd.Timestamp("2024-01-05")
    return SignalPlanInput(PortfolioState(0., {"2330.TW": 10}),
        {"2330.TW": EngineStop(95., 110., .1)}, {}, frozenset(),
        OddLotResearchConfig(strategy="momentum", rebalance_every=20), BacktestConfig(),
        day, 1, pd.DataFrame({"2330.TW": [90.]}, index=[day]),
        pd.Series({"2330.TW": True}), pd.Series({"2330.TW": 90.}),
        pd.Series({"2330.TW": 90.}), pd.Series({"2330.TW": 1000000.}), 0., False)


def test_daily_stop_runs_off_rebalance_day_and_inputs_remain_unchanged(monkeypatch):
    def forbidden(*args):
        raise AssertionError("model must not run on this offset")
    monkeypatch.setattr("quant_fund_lab.odd_lot_research._targets", forbidden)
    inputs = _inputs()
    result = plan_close_signals(inputs)
    assert result.pending["2330.TW"].side == "SELL"
    assert result.pending["2330.TW"].quantity == 10
    assert result.signals[0]["reason"] == "stop" and not inputs.pending
    result.stops["2330.TW"].stop = 1
    assert inputs.stops["2330.TW"].stop == 95


def test_unobserved_close_does_not_trigger_stop_and_passive_entry_does_not_restart(monkeypatch):
    inputs = _inputs()
    missing = replace(inputs, observed_open=pd.Series({"2330.TW": float("nan")}))
    assert not plan_close_signals(missing).signals
    def forbidden(*args):
        raise AssertionError("passive first entry must not restart")
    monkeypatch.setattr("quant_fund_lab.odd_lot_research._targets", forbidden)
    passive = replace(inputs, stops={}, portfolio=PortfolioState(1000.), session_offset=20,
                      research=replace(inputs.research, strategy="equal_weight"), passive_submitted=True)
    assert not plan_close_signals(passive).signals


def test_future_or_misaligned_history_is_rejected_before_models():
    inputs = _inputs()
    future = pd.concat([inputs.history, pd.DataFrame({"2330.TW": [200.]},
        index=[pd.Timestamp("2024-01-08")])])
    with pytest.raises(ValueError, match="end exactly"):
        plan_close_signals(replace(inputs, history=future))
    for value in (-1, True):
        with pytest.raises(ValueError, match="origin"):
            plan_close_signals(replace(inputs, session_offset=value))
