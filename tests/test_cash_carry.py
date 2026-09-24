import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quant_fund_lab.backtest import run_backtest
from quant_fund_lab.cash_carry import accrue_base_cash_interest
from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.execution import PortfolioState
from quant_fund_lab.paper import historical_vs_paper_replay
from quant_fund_lab.paper_live import replay_targets_persistently
from quant_fund_lab.reporting import export_research_report, verify_research_report


def _all_cash_data():
    data = synthetic_market_data(symbols=("AAA", "BBB"), periods=155, seed=71)
    return replace(
        data,
        membership=pd.DataFrame(False, index=data.close.index, columns=data.symbols),
        market_codes=None,
        currency_codes=None,
        exchange=None,
    )


def test_cash_yield_default_preserves_positional_base_currency():
    config = BacktestConfig(100_000.0, "USD")
    assert config.base_currency == "USD"
    assert config.cash_annual_yield == 0.0


def test_base_cash_carry_uses_calendar_days_but_excludes_receivables():
    state = PortfolioState(cash=100.0, receivable_value=900.0)
    amount = accrue_base_cash_interest(
        state,
        pd.Timestamp("2026-01-02"),
        pd.Timestamp("2026-01-05"),
        0.10,
    )

    assert amount == pytest.approx(100.0 * 0.10 * 3 / 365.0)
    assert state.cash == pytest.approx(100.0 + amount)
    assert state.receivable_value == pytest.approx(900.0)


def test_act365_cash_carry_uses_calendar_dates_across_us_dst():
    state = PortfolioState(cash=365.0)
    interest = accrue_base_cash_interest(
        state,
        pd.Timestamp("2026-03-06", tz="America/New_York"),
        pd.Timestamp("2026-03-09", tz="America/New_York"),
        1.0,
    )
    assert interest == pytest.approx(3.0)


def test_all_cash_backtest_credits_interest_before_next_open():
    data = _all_cash_data()
    config = BacktestConfig(
        initial_cash=100_000.0,
        cash_annual_yield=0.06,
        strategy=StrategyConfig(warmup_days=80, rebalance_every=10),
    )
    result = run_backtest(data, config)
    zero = run_backtest(data, replace(config, cash_annual_yield=0.0))
    equity = result.equity_curve

    assert result.fills.empty
    assert equity["cash_interest"].iloc[0] == 0.0
    assert zero.equity_curve["equity"].eq(100_000.0).all()
    assert zero.equity_curve["cash_interest"].eq(0.0).all()
    expected_cash = 100_000.0
    for previous, current in zip(equity.index[:-1], equity.index[1:]):
        expected_interest = expected_cash * 0.06 * (current - previous).days / 365.0
        assert equity.at[current, "cash_interest"] == pytest.approx(expected_interest)
        expected_cash += expected_interest
        assert equity.at[current, "equity"] == pytest.approx(expected_cash)
    assert equity["cash_interest"].sum() == pytest.approx(expected_cash - 100_000.0)


def test_cash_yield_flows_through_out_of_sample_paper_comparison():
    data = _all_cash_data()
    config = BacktestConfig(
        initial_cash=100_000.0,
        cash_annual_yield=0.05,
        strategy=StrategyConfig(warmup_days=80, rebalance_every=10),
    )
    comparison = historical_vs_paper_replay(data, config)
    assert comparison.backtest.equity_curve["cash_interest"].sum() > 0.0
    assert comparison.paper_replay.equity_curve["cash_interest"].sum() > 0.0
    assert comparison.paper_replay.equity_curve["equity"].iloc[0] == 100_000.0


def test_cash_carry_report_is_hash_verifiable(tmp_path):
    data = _all_cash_data()
    config = BacktestConfig(
        initial_cash=100_000.0,
        cash_annual_yield=0.05,
        strategy=StrategyConfig(warmup_days=80, rebalance_every=10),
    )
    result = run_backtest(data, config)
    root = tmp_path / "cash-report"
    _, hashes = export_research_report(result, config, "cash-dataset", root)
    summary = json.loads((root / "cash_carry_summary.json").read_text(encoding="utf-8"))
    assert summary["annual_yield_assumption"] == pytest.approx(0.05)
    assert summary["interest_credited_base"] == pytest.approx(
        result.equity_curve["cash_interest"].sum()
    )
    assert summary["interest_credit_sessions"] > 0
    assert "cash_carry_summary.json" in hashes
    assert verify_research_report(root)
    (root / "cash_carry_summary.json").write_text("tamper", encoding="utf-8")
    assert not verify_research_report(root)


def test_cash_yield_rejects_invalid_assumptions_and_nonadvancing_sessions():
    for rate in (-0.01, 1.01, np.nan, np.inf):
        with pytest.raises(ValueError, match="cash_annual_yield"):
            BacktestConfig(cash_annual_yield=rate)
    with pytest.raises(ValueError, match="advance"):
        accrue_base_cash_interest(
            PortfolioState(cash=100.0),
            pd.Timestamp("2026-01-05"),
            pd.Timestamp("2026-01-05"),
            0.05,
        )


def test_persistent_replay_supports_nonzero_cash_yield(tmp_path):
    data = _all_cash_data()
    config = BacktestConfig(cash_annual_yield=0.05)
    signals = pd.DataFrame(
        0.0, index=data.close.index[80:81], columns=data.symbols
    )
    path = tmp_path / "cash-interest.sqlite"
    ledger = replay_targets_persistently(data, signals, config, path)
    try:
        assert ledger.nav_history()["cumulative_cash_interest"].iloc[-1] > 0.0
        assert not ledger.cash_interest_credits().empty
    finally:
        ledger.close()
