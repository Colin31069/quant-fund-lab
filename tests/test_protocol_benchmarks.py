"""Protocol v2 declares, gates and reports tradable benchmarks without changing v1."""
import hashlib
import json
import sqlite3
from dataclasses import asdict, replace

import pandas as pd
import pytest
from test_registered_odd_lot_study import SOURCE, _study

from quant_fund_lab.odd_lot_benchmarks import BenchmarkSpec
from quant_fund_lab.odd_lot_protocol import (
    ExperimentRegistry,
    freeze_protocol,
    protocol_from_studies,
    run_registered_study,
)
from quant_fund_lab.odd_lot_protocol.benchmark import benchmark_from_plan
from quant_fund_lab.odd_lot_protocol.types import canonical_json
from quant_fund_lab.odd_lot_study import load_frozen_odd_lot_study, verify_odd_lot_study_report


def _v2(tmp_path, monkeypatch, *, ready):
    directory, parent, _ = _study(tmp_path, monkeypatch, ready=ready)
    _, metadata = load_frozen_odd_lot_study(directory)
    benchmark = BenchmarkSpec(parent.benchmark,metadata["backtest_config"]["initial_cash"],10,0.10,
                               "Explicit fixture ETF assumptions; historical legal rules not certified.")
    protocol = protocol_from_studies((directory,),periods=parent.periods,selection=parent.selection,
        execution=parent.execution,declared_at=parent.declared_at,parent_protocol_id=parent.protocol_id,
        benchmark_spec=benchmark)
    assert benchmark_from_plan(parent.analysis_plan_json) is None
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        registry.register_protocol(parent)
    return directory, protocol, benchmark, freeze_protocol(protocol,tmp_path / "protocols")


def test_ready_v2_protocol_exports_same_cost_benchmark_and_reproduces_results(tmp_path, monkeypatch):
    directory, protocol, benchmark, frozen = _v2(tmp_path,monkeypatch,ready=True)
    inputs = {"studies_directory":directory.parent,"registry_path":tmp_path/"registry.sqlite",
              "source_directory":SOURCE}
    first = run_registered_study(frozen,protocol.candidates[0].candidate_id,**inputs)
    second = run_registered_study(frozen,protocol.candidates[0].candidate_id,**inputs)
    assert first.attempt.status == second.attempt.status == "succeeded"
    assert first.attempt.result_fingerprint == second.attempt.result_fingerprint
    assert benchmark_from_plan(protocol.analysis_plan_json) == benchmark
    report = first.report
    assert verify_odd_lot_study_report(report)
    assert json.loads((report/"benchmark_specs.json").read_text()) == {benchmark.symbol:asdict(benchmark)}
    comparison = pd.read_csv(report/"comparison.csv")
    row = comparison[comparison.strategy.eq(benchmark.result_name)].iloc[0]
    assert row.comparison_basis == "tradable_benchmark_with_same_costs"
    assert row.ending_invested_fraction > 0 and row.ending_cash_fraction > 0
    assert "no_cost_total_return_reference" in set(comparison.comparison_basis)
    curve = pd.read_csv(report/f"validation_{benchmark.result_name}_equity_curve.csv",index_col=0)
    baseline = pd.read_csv(report/"validation_equal_weight_equity_curve.csv",index_col=0)
    assert curve.index.equals(baseline.index)
    orders = pd.read_csv(report/f"validation_{benchmark.result_name}_orders.csv")
    assert len(orders) == 1 and orders.iloc[0].status == "partial_expired"
    with sqlite3.connect(report/"study_ledger.sqlite") as connection:
        settings = json.loads(connection.execute("SELECT settings_json FROM accounts WHERE account_id=?",
            (f"validation/{benchmark.result_name}",)).fetchone()[0])
        assert settings["research"]["instrument_rules"][benchmark.symbol] == benchmark.instrument_rule


def test_blocked_period_does_not_compute_the_declared_benchmark(tmp_path, monkeypatch):
    directory, protocol, _benchmark, frozen = _v2(tmp_path,monkeypatch,ready=False)
    import quant_fund_lab.odd_lot_protocol.benchmark as module

    def forbidden(*_args,**_kwargs):
        pytest.fail("blocked inputs reached tradable benchmark performance")

    monkeypatch.setattr(module,"run_tradable_benchmark",forbidden)
    result = run_registered_study(frozen,protocol.candidates[0].candidate_id,
        studies_directory=directory.parent,registry_path=tmp_path/"registry.sqlite",source_directory=SOURCE)
    assert result.attempt.status == "blocked"
    assert verify_odd_lot_study_report(result.report)
    unavailable = json.loads((result.report/"unavailable.json").read_text())
    assert len(unavailable) == 15
    assert all(f"{period.name}/tradable_benchmark" in unavailable for period in protocol.periods)
    assert (result.report/"comparison.csv").read_text().strip() == ""


def test_benchmark_capital_and_rehashed_spec_cannot_disagree_with_protocol(tmp_path, monkeypatch):
    directory, protocol, benchmark, frozen = _v2(tmp_path,monkeypatch,ready=False)
    with pytest.raises(ValueError,match="capital and benchmark"):
        protocol_from_studies((directory,),periods=protocol.periods,selection=protocol.selection,
            execution=protocol.execution,declared_at=protocol.declared_at,
            benchmark_spec=replace(benchmark,initial_cash=50000))
    result = run_registered_study(frozen,protocol.candidates[0].candidate_id,
        studies_directory=directory.parent,registry_path=tmp_path/"registry.sqlite",source_directory=SOURCE)
    path = result.report/"benchmark_specs.json"
    payload = json.loads(path.read_text())
    payload[benchmark.symbol]["sell_tax_bps"] = 99
    path.write_text(canonical_json(payload))
    manifest_path = result.report/"report_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.pop("report_id")
    manifest["files"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest["report_id"] = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    manifest_path.write_text(canonical_json(manifest))
    assert not verify_odd_lot_study_report(result.report)
