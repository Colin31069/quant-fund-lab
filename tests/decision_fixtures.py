"""Offline v5 fixtures with explicit lenient test policies, never a strategy-validity claim."""
from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd
from test_registered_odd_lot_study import SOURCE
from test_twse_readiness_frozen import _ready_official_bundle

from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.odd_lot_benchmarks import BenchmarkSpec
from quant_fund_lab.odd_lot_decisions import DecisionPolicy
from quant_fund_lab.odd_lot_protocol import (
    ExperimentRegistry,
    ProtocolPeriod,
    SelectionRule,
    capture_execution_identity,
    freeze_protocol,
    protocol_from_studies,
    run_registered_study,
)
from quant_fund_lab.odd_lot_research import OddLotResearchConfig
from quant_fund_lab.odd_lot_study import freeze_odd_lot_study


def decision_fixture(tmp_path, monkeypatch, *, positive=False, count=1, prices=None, exploration=False):
    import quant_fund_lab.odd_lot_study as module

    _, symbols, dates, inputs = _ready_official_bundle(tmp_path,start="2023-01-01",end="2024-12-31",
        sessions=(360 if positive else 180) if exploration else (280 if positive else 160),
        price=prices if prices is not None else "10000" if positive else "100")
    boundary = 200 if positive else 140
    validation_end = boundary + (80 if positive else 20) if exploration else len(dates)
    periods = {"development":(str(dates[120].date()),str(dates[boundary-1].date())),
               "validation":(str(dates[boundary].date()),str(dates[validation_end-1].date()))}
    if exploration:
        periods["exploration"] = (str(dates[validation_end].date()), str(dates[-1].date()))
    monkeypatch.setattr(module,"PERIODS",periods)
    research = OddLotResearchConfig(min_commission=0,commission_bps=0,slippage_bps=0,
        fill_fraction=1,max_participation=1,impact_coefficient=0,rebalance_every=1,
        max_weight=.011 if positive else .2)
    base = BacktestConfig(initial_cash=1000000 if positive else 100000,base_currency="TWD",
                          strategy=StrategyConfig(warmup_days=30))
    if positive:
        def targets(history, eligible, research, strategy, previous):
            weight = research.max_weight if len(history)%2 == 0 else 0
            return pd.Series(1.0,index=history.columns),pd.Series(weight,index=history.columns)
        monkeypatch.setattr("quant_fund_lab.odd_lot_research._targets",targets)
    studies = tuple(freeze_odd_lot_study(inputs.data,tmp_path/"studies",symbols=tuple(symbols[:2]),
        benchmark=symbols[2],source="twse_official",source_provenance=inputs.provenance,
        source_files=inputs.source_files,source_hashes=inputs.source_hashes,quality_issues=[],
        research=replace(research,risk_budget=2000+i*100),base_config=base) for i in range(count))
    policy = DecisionPolicy("annual_return",1,-1,-1,1,require_benchmark_outperformance=False)
    selection = SelectionRule("annual_return","Fixture-only executable thresholds.","Retain all missing evidence.")
    protocol_periods = tuple(ProtocolPeriod(name,start,end,"development_selection" if name == "development"
        else "historical_exploration" if name == "exploration" else "validation_check",
        "accessed","Explicit offline test, not an unseen sample.") for name,(start,end) in periods.items())
    args = {"periods":protocol_periods,"selection":selection,"execution":capture_execution_identity(SOURCE),
            "declared_at":datetime.now(timezone.utc).isoformat(),
            "benchmark_spec":BenchmarkSpec(symbols[2],base.initial_cash,0,.1,"Explicit offline zero ETF tax fixture."),
            "risk_diagnostics":True,"matched_sensitivity":True}
    parent = protocol_from_studies(studies,**args)
    freeze_protocol(parent,tmp_path/"protocols")
    protocol = protocol_from_studies(studies,**args,decision_policy=policy,parent_protocol_id=parent.protocol_id)
    frozen = freeze_protocol(protocol,tmp_path/"protocols")
    with ExperimentRegistry(tmp_path/"registry.sqlite") as registry:
        registry.register_protocol(parent)
        registry.register_protocol(protocol)
    return studies,protocol,frozen,args


def run_candidate(tmp_path, protocol, frozen, candidate=None):
    return run_registered_study(frozen,candidate or protocol.candidates[0].candidate_id,
        registry_path=tmp_path/"registry.sqlite",studies_directory=tmp_path/"studies",source_directory=SOURCE)
