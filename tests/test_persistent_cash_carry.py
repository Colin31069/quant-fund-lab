from dataclasses import replace

import pandas as pd
import pytest

from quant_fund_lab.backtest import run_backtest
from quant_fund_lab.config import BacktestConfig, MarketCostConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.paper_live import PaperLedger, replay_targets_persistently


def _case():
    data = synthetic_market_data(symbols=("AAA", "BBB"), periods=54, seed=41)
    data = replace(
        data,
        membership=pd.DataFrame(False, index=data.close.index, columns=data.symbols),
        market_codes=None,
        currency_codes=None,
        exchange=None,
    )
    config = BacktestConfig(
        initial_cash=100_000.0,
        base_currency="USD",
        cash_annual_yield=0.05,
        strategy=StrategyConfig(warmup_days=20, rebalance_every=5),
    )
    targets = pd.DataFrame(
        0.0, index=data.close.index[19:20], columns=data.symbols
    )
    return data, config, targets


def test_persistent_interest_matches_historical_all_cash_and_reconciles(tmp_path):
    data, config, targets = _case()
    historical = run_backtest(data, config)
    ledger = replay_targets_persistently(
        data, targets, config, tmp_path / "all-cash.sqlite"
    )
    try:
        nav = ledger.nav_history()
        credits = ledger.cash_interest_credits()
        assert nav.index.equals(historical.equity_curve.index)
        assert len(credits) == len(nav) - 1
        assert nav.iloc[0]["cash_interest"] == pytest.approx(0.0)
        assert nav["cash_interest"].to_numpy() == pytest.approx(
            historical.equity_curve["cash_interest"].to_numpy()
        )
        assert nav["equity"].to_numpy() == pytest.approx(
            historical.equity_curve["equity"].to_numpy()
        )
        assert nav["cash_interest"].sum() == pytest.approx(
            nav.iloc[-1]["cumulative_cash_interest"]
        )
        assert nav.iloc[-1]["realized_pnl"] == pytest.approx(
            nav.iloc[-1]["cumulative_cash_interest"]
        )
        assert nav["reconciliation_error"].abs().max() < 1e-8
        assert credits["interest_base"].gt(0.0).all()
        assert credits["accrual_days"].max() >= 3
    finally:
        ledger.close()


def test_replay_resumes_without_duplicate_interest_or_completed_sessions(tmp_path):
    data, config, targets = _case()
    path = tmp_path / "resume.sqlite"
    prefix = data.slice(end=data.close.index[34])
    ledger = replay_targets_persistently(prefix, targets, config, path)
    try:
        prior_nav = ledger.nav_history()
        prior_credit_count = len(ledger.cash_interest_credits())
        assert prior_credit_count == len(prior_nav) - 1
    finally:
        ledger.close()

    # Simulate a crash after the credit committed but before the session's NAV.
    next_day = data.close.index[35]
    with PaperLedger(path, base_currency="USD") as reopened:
        reopened.ensure_cash_annual_yield(config.cash_annual_yield)
        interest = reopened.accrue_cash_interest(next_day)
        credited_cash = reopened.cash
        assert interest > 0.0
        assert reopened.accrue_cash_interest(next_day) == pytest.approx(interest)
        assert reopened.cash == pytest.approx(credited_cash)
        assert len(reopened.cash_interest_credits()) == prior_credit_count + 1

    resumed = replay_targets_persistently(data, targets, config, path, reset=False)
    try:
        nav = resumed.nav_history()
        credits = resumed.cash_interest_credits()
        historical = run_backtest(data, config).equity_curve
        assert len(nav) == len(historical)
        assert len(credits) == len(nav) - 1
        assert not credits["timestamp"].duplicated().any()
        assert nav.loc[next_day, "cash_interest"] == pytest.approx(interest)
        assert nav["equity"].to_numpy() == pytest.approx(
            historical["equity"].to_numpy()
        )
        assert nav["reconciliation_error"].abs().max() < 1e-8
    finally:
        resumed.close()


def test_locked_interest_assumption_cannot_change_on_reopen(tmp_path):
    data, config, targets = _case()
    path = tmp_path / "locked.sqlite"
    ledger = replay_targets_persistently(
        data.slice(end=data.close.index[24]), targets, config, path
    )
    try:
        original_cash = ledger.cash
        original_credits = len(ledger.cash_interest_credits())
    finally:
        ledger.close()
    with pytest.raises(ValueError, match="does not match"):
        replay_targets_persistently(
            data,
            targets,
            replace(config, cash_annual_yield=0.06),
            path,
            reset=False,
        )
    with PaperLedger(path, base_currency="USD") as reopened:
        assert reopened.cash == pytest.approx(original_cash)
        assert len(reopened.cash_interest_credits()) == original_credits


def test_cash_interest_replay_rejects_partially_posted_non_interest_session(tmp_path):
    data, config, targets = _case()
    path = tmp_path / "incomplete.sqlite"
    ledger = replay_targets_persistently(
        data.slice(end=data.close.index[24]), targets, config, path
    )
    try:
        next_day = data.close.index[25]
        ledger.accrue_cash_interest(next_day)
        before = ledger.cash
        ledger.connection.execute(
            "INSERT INTO terminal_events("
            "timestamp, symbol, quantity, reference_price, terminal_return, "
            "proceeds, realized_pnl_base"
            ") VALUES(?, 'AAA', 1, 100, -1, 0, 0)",
            (next_day.isoformat(),),
        )
        ledger.connection.commit()
    finally:
        ledger.close()
    with pytest.raises(ValueError, match="incomplete persistent session"):
        replay_targets_persistently(data, targets, config, path, reset=False)
    with PaperLedger(path, base_currency="USD") as reopened:
        assert reopened.cash == pytest.approx(before)
        assert reopened.cash_interest_credits()["timestamp"].eq(next_day).sum() == 1


def test_persistent_zero_yield_remains_zero_and_audited(tmp_path):
    data, config, targets = _case()
    config = replace(config, cash_annual_yield=0.0)
    ledger = replay_targets_persistently(
        data, targets, config, tmp_path / "zero.sqlite"
    )
    try:
        nav = ledger.nav_history()
        credits = ledger.cash_interest_credits()
        assert nav["cash_interest"].eq(0.0).all()
        assert nav["cumulative_cash_interest"].eq(0.0).all()
        assert credits["interest_base"].eq(0.0).all()
        assert ledger.cash == pytest.approx(config.initial_cash)
    finally:
        ledger.close()


def test_restart_does_not_repeat_completed_order_fills(tmp_path):
    data = synthetic_market_data(symbols=("AAA", "BBB"), periods=38, seed=55)
    config = BacktestConfig(
        initial_cash=100_000.0,
        base_currency="USD",
        cash_annual_yield=0.05,
        strategy=StrategyConfig(warmup_days=20),
        us_costs=MarketCostConfig(
            commission_bps=0.0,
            sec_fee_per_million=0.0,
            slippage_bps=0.0,
            impact_coefficient=0.0,
            max_participation=1.0,
            lot_size=1,
        ),
    )
    targets = pd.DataFrame(
        [{"AAA": 0.30, "BBB": 0.0}], index=[data.close.index[19]]
    )
    path = tmp_path / "filled-resume.sqlite"
    first = replay_targets_persistently(
        data.slice(end=data.close.index[24]),
        targets,
        config,
        path,
    )
    try:
        original_fills = first.fills()
        original_orders = first.orders()
        assert len(original_fills) == 1
        assert original_orders.iloc[0]["status"] == "FILLED"
    finally:
        first.close()

    resumed = replay_targets_persistently(data, targets, config, path, reset=False)
    try:
        fills = resumed.fills()
        orders = resumed.orders()
        nav = resumed.nav_history()
        assert fills.equals(original_fills)
        assert orders.equals(original_orders)
        assert len(nav) == len(data.close.index[19:])
        assert len(resumed.cash_interest_credits()) == len(nav) - 1
        assert nav["reconciliation_error"].abs().max() < 1e-8
    finally:
        resumed.close()
