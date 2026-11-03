"""Matched scenarios use actual strategy/ETF matching and retain the entire finite grid."""
import json
from dataclasses import asdict, replace

import pandas as pd
import pytest

from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import MarketData
from quant_fund_lab.market_calendar import expected_market_sessions
from quant_fund_lab.odd_lot_benchmarks import BenchmarkSpec
from quant_fund_lab.odd_lot_protocol.benchmark import add_tradable_benchmarks
from quant_fund_lab.odd_lot_research import OddLotResearchConfig, run_odd_lot_research
from quant_fund_lab.odd_lot_sensitivity.engine import run_matched_sensitivity
from quant_fund_lab.odd_lot_sensitivity.types import SensitivityScenario
from quant_fund_lab.odd_lot_study import OddLotStudyResult, _subset

SCENARIOS = (SensitivityScenario(0,0,1), SensitivityScenario(0,0,.5), SensitivityScenario(20,5,.5))


def _inputs(end=159):
    dates = pd.DatetimeIndex(expected_market_sessions("TW", "2024-01-01", "2024-12-31").sessions)[:160]
    stocks, benchmark = ["2330.TW", "2317.TW"], "0050.TW"
    raw = pd.DataFrame(100.0, index=dates, columns=[*stocks, benchmark])
    raw[benchmark] = 200
    raw.loc[dates[120]:,benchmark] = 210
    for i in range(120, len(dates)):
        raw.loc[dates[i],stocks] = [100+(i-119)*.1, 100+(i-119)*.2]
    opening = raw.shift(1).fillna(raw.iloc[0])
    data = MarketData(opening,raw,raw*100000,raw_open=opening,raw_close=raw).slice(end=dates[end])
    research = OddLotResearchConfig(min_commission=0,commission_bps=0,slippage_bps=0,
        impact_coefficient=0,fill_fraction=1,max_participation=1)
    base = BacktestConfig(initial_cash=100000,base_currency="TWD",strategy=StrategyConfig(warmup_days=30))
    spec = BenchmarkSpec(benchmark,100000,0,.10,"Explicit offline test assumptions.")
    start, finish = str(dates[120].date()), str(dates[end].date())
    metadata = {"research_config":asdict(research),"backtest_config":asdict(base),
        "symbols":stocks,"benchmark":benchmark,"periods":{"validation":[start,finish]},
        "readiness":{"periods":[{"period":"validation","status":"ready"}]}}
    results = {("validation", strategy):run_odd_lot_research(_subset(data, stocks),replace(research,strategy=strategy),
        base,start=start,end=finish) for strategy in ("ensemble","momentum","equal_weight")}
    study = OddLotStudyResult("fixture", "fixture",pd.DataFrame(),pd.DataFrame(),results,{},False)
    study = add_tradable_benchmarks(data,metadata,study,spec)
    return data, metadata, study, spec, dates


def test_cost_and_fill_scenarios_reconcile_with_hand_calculation():
    data, metadata, study, spec, _ = _inputs()
    result = run_matched_sensitivity(data,metadata,study,spec,SCENARIOS)
    matched = result.matched_sensitivity
    assert len(matched.outcomes) == len(matched.accounts) == 9 and matched.status == "succeeded"
    assert len(result.sensitivity) == 9
    primary = study.results[("validation",spec.result_name)]
    full = matched.accounts[(SCENARIOS[0].scenario_id,spec.result_name)]
    half = matched.accounts[(SCENARIOS[1].scenario_id,spec.result_name)]
    paid = matched.accounts[(SCENARIOS[2].scenario_id,spec.result_name)]
    assert full is primary and full.fills.iloc[0].quantity == 500
    assert full.equity_curve.iloc[-1].equity == 105000
    assert half.fills.iloc[0].quantity == 250 and half.equity_curve.iloc[-1].equity == 102500
    assert half.equity_curve.iloc[-1]["cash"] == 50000
    assert len(full.orders) == len(half.orders) == len(paid.orders) == 1
    assert half.orders.iloc[0].expired_quantity == 250
    assert paid.fills.iloc[0].fill_price == 200.1 and paid.fills.iloc[0].commission == 20
    assert paid.equity_curve.iloc[-1].equity == 102455
    outcome = next(row for row in matched.outcomes if row.strategy == spec.result_name and row.scenario == SCENARIOS[2])
    summary = json.loads(outcome.summaries_json)
    assert summary["commission"] == 20 and summary["slippage_cost"] == pytest.approx(25)
    assert summary["ending_equity"] == 102455 and summary["ending_invested_fraction"] == pytest.approx(52500/102455)
    assert summary["closed_count"] == 0 and not summary["sample_sufficient"]
    assert "profit_factor" in outcome.to_dict()["undefined_metrics"]
    assert primary.config.min_commission == 0  # Scenario copies never mutate primary inputs.
    for (scenario_id, strategy), account in matched.accounts.items():
        assert account.equity_curve.index.equals(primary.equity_curve.index)
        scenario = next(row for row in SCENARIOS if row.scenario_id == scenario_id)
        assert account.config.fill_fraction == scenario.fill_fraction
        assert account.backtest_config.tw_costs.slippage_bps == scenario.slippage_bps
        assert account.backtest_config.tw_costs.min_commission == scenario.min_commission


def test_truncating_future_keeps_earlier_signals_orders_and_fills():
    data, metadata, study, spec, dates = _inputs()
    full = run_matched_sensitivity(data,metadata,study,spec,SCENARIOS).matched_sensitivity
    data, metadata, study, spec, _ = _inputs(end=145)
    short = run_matched_sensitivity(data,metadata,study,spec,SCENARIOS).matched_sensitivity
    for key, account in short.accounts.items():
        for name in ("signals","orders","fills"):
            expected = getattr(full.accounts[key],name)
            actual = getattr(account,name)
            if not expected.empty:
                expected = expected.loc[pd.to_datetime(expected.timestamp).le(dates[145])].reset_index(drop=True)
            pd.testing.assert_frame_equal(actual,expected)


def test_one_failed_scenario_does_not_hide_other_outcomes(monkeypatch):
    import quant_fund_lab.odd_lot_sensitivity.engine as module

    data, metadata, study, spec, _ = _inputs()
    original = module.run_tradable_benchmark
    def fail(data, spec, research, *args, **kwargs):
        if research.min_commission == 20:
            raise ValueError("injected ETF scenario failure")
        return original(data,spec,research,*args,**kwargs)
    monkeypatch.setattr(module,"run_tradable_benchmark",fail)
    matched = run_matched_sensitivity(data,metadata,study,spec,SCENARIOS).matched_sensitivity
    assert len(matched.outcomes) == 9 and len(matched.accounts) == 8 and matched.status == "failed"
    failure = [row for row in matched.outcomes if row.status == "failed"]
    assert len(failure) == 1 and failure[0].strategy == spec.result_name
    assert "injected" in failure[0].reason and failure[0].summaries_json == "{}"


def test_blocked_inputs_never_reach_scenario_performance(monkeypatch):
    import quant_fund_lab.odd_lot_sensitivity.engine as module

    data, metadata, study, spec, _ = _inputs()
    metadata["readiness"]["periods"][0]["status"] = "blocked"
    def forbidden(*args,**kwargs):
        pytest.fail("blocked sensitivity executed")
    monkeypatch.setattr(module,"run_odd_lot_research",forbidden)
    monkeypatch.setattr(module,"run_tradable_benchmark",forbidden)
    matched = run_matched_sensitivity(data,metadata,study,spec,SCENARIOS).matched_sensitivity
    assert matched.status == "blocked" and not matched.accounts
    assert len(matched.outcomes) == 9 and all(row.status == "blocked" for row in matched.outcomes)
    assert all(not json.loads(row.summaries_json) for row in matched.outcomes)


@pytest.mark.parametrize("values",[(True,0,1),(0,float("inf"),1),(0,0,0),(-1,0,.5)])
def test_scenarios_reject_unknown_nonfinite_or_invalid_assumptions(values):
    with pytest.raises(ValueError):
        SensitivityScenario(*values)
