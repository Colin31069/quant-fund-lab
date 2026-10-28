"""M11-7: independent read-only SQL ledger reconciliation and replay gate."""

import json
import sqlite3
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quant_fund_lab.config import (
    BacktestConfig,
    DividendWithholdingConfig,
    MarketCostConfig,
    StrategyConfig,
)
from quant_fund_lab.data import MarketData, synthetic_market_data
from quant_fund_lab.fx import attach_fx_rates
from quant_fund_lab.paper_live import PaperLedger, replay_targets_persistently


def _case():
    data = synthetic_market_data(symbols=("AAA", "BBB"), periods=35, seed=83)
    config = BacktestConfig(
        initial_cash=100_000.0,
        base_currency="USD",
        cash_annual_yield=0.05,
        strategy=StrategyConfig(warmup_days=20),
    )
    targets = pd.DataFrame(
        [{"AAA": 0.25, "BBB": 0.0}], index=[data.close.index[19]]
    )
    return data, config, targets


def _prefix(tmp_path):
    data, config, targets = _case()
    path = tmp_path / "audited.sqlite"
    first = replay_targets_persistently(
        data.slice(end=data.close.index[24]), targets, config, path
    )
    try:
        nav = first.nav_history()
        assert len(nav) == 6
        assert not first.fills().empty
        assert len(first.cash_interest_credits()) == len(nav) - 1
    finally:
        first.close()
    return data, config, targets, path


def test_clean_ledger_audit_is_read_only_and_matches_existing_sql(tmp_path):
    data, config, targets, path = _prefix(tmp_path)
    with PaperLedger(path, base_currency="USD") as ledger:
        before = ledger.connection.total_changes
        report = ledger.audit_integrity()
        assert ledger.connection.total_changes == before
        assert report.is_valid
        assert report.issues == ()
        assert report.nav_sessions == 6
        assert report.fills == len(ledger.fills())
        assert report.position_marks > 0
        assert report.cash_credits == 5
        assert ledger.audit_integrity() == report

    continued = replay_targets_persistently(data, targets, config, path, reset=False)
    try:
        assert continued.audit_integrity().is_valid
        assert continued.audit_integrity().nav_sessions == len(data.close.index[19:])
    finally:
        continued.close()


@pytest.mark.parametrize(
    ("statement", "identifier"),
    [
        ("UPDATE nav SET equity=equity+3 WHERE timestamp=?", "nav_equity_mismatch"),
        (
            "UPDATE nav SET cash_interest=cash_interest+3 WHERE timestamp=?",
            "daily_cash_interest_mismatch",
        ),
        (
            "UPDATE nav SET cumulative_cash_interest=cumulative_cash_interest+3 WHERE timestamp=?",
            "cumulative_cash_interest_mismatch",
        ),
        (
            "UPDATE nav SET cumulative_fees=cumulative_fees+3 WHERE timestamp=?",
            "cumulative_fees_mismatch",
        ),
        (
            "UPDATE nav SET cumulative_slippage=cumulative_slippage+3 WHERE timestamp=?",
            "cumulative_slippage_mismatch",
        ),
        (
            "UPDATE nav SET market_value=market_value+3 WHERE timestamp=?",
            "nav_market_value_mismatch",
        ),
        (
            "UPDATE nav SET unrealized_pnl=unrealized_pnl+3 WHERE timestamp=?",
            "nav_unrealized_pnl_mismatch",
        ),
        (
            (
                "UPDATE position_marks SET market_value_base=market_value_base+3 "
                "WHERE timestamp=? AND symbol='AAA'"
            ),
            "position_mark_arithmetic_mismatch",
        ),
        (
            "UPDATE fills SET fees_local=fees_local+3 WHERE timestamp=?",
            "fill_fx_accounting_mismatch",
        ),
        (
            "UPDATE fills SET symbol='BBB' WHERE timestamp=?",
            "fill_order_mismatch",
        ),
    ],
)
def test_corrupted_historical_accounting_rejects_new_sessions(
    tmp_path, statement, identifier
):
    data, config, targets, path = _prefix(tmp_path)
    filled_day = data.close.index[20].isoformat()
    with sqlite3.connect(path) as db:
        db.execute(statement, (filled_day,))
    with PaperLedger(path, base_currency="USD") as ledger:
        report = ledger.audit_integrity()
        assert not report.is_valid
        assert any(identifier in issue for issue in report.issues)
        original_nav_count = len(ledger.nav_history())
        original_fill_count = len(ledger.fills())
        original_commits = ledger.session_commits()

    with pytest.raises(ValueError, match="accounting integrity audit failed before replay"):
        replay_targets_persistently(data, targets, config, path, reset=False)

    with PaperLedger(path, base_currency="USD") as ledger:
        assert len(ledger.nav_history()) == original_nav_count
        assert len(ledger.fills()) == original_fill_count
        assert ledger.session_commits().equals(original_commits)


def test_latest_position_and_cash_metadata_corruption_are_detected(tmp_path):
    data, config, targets, path = _prefix(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE positions SET quantity=quantity+1 WHERE symbol='AAA'"
        )
        db.execute(
            "UPDATE metadata SET value=? WHERE key='cash'", ("123456.0",)
        )
    with PaperLedger(path, base_currency="USD") as ledger:
        report = ledger.audit_integrity()
        assert not report.is_valid
        assert any("latest_position_mismatch" in issue for issue in report.issues)
        assert any("latest_cash_metadata_mismatch" in issue for issue in report.issues)
    with pytest.raises(ValueError, match="accounting integrity audit failed"):
        replay_targets_persistently(data, targets, config, path, reset=False)


def test_invalid_order_and_foreign_key_violations_are_detected(tmp_path):
    data, config, targets, path = _prefix(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE orders SET remaining_qty=requested_qty+1")
        db.execute("UPDATE fills SET order_id=99999")
    with PaperLedger(path, base_currency="USD") as ledger:
        issues = ledger.audit_integrity().issues
        assert any("invalid_order_balance" in issue for issue in issues)
        assert any("foreign_key_violation" in issue for issue in issues)
        assert any("fill_order_mismatch" in issue for issue in issues)
    with pytest.raises(ValueError, match="accounting integrity audit failed"):
        replay_targets_persistently(data, targets, config, path, reset=False)


def test_missing_completion_marker_is_reported_read_only(tmp_path):
    data, config, targets, path = _prefix(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute(
            "DELETE FROM session_commits WHERE timestamp=?",
            (data.close.index[21].isoformat(),),
        )
    with PaperLedger(path, base_currency="USD") as ledger:
        report = ledger.audit_integrity()
        assert any("missing_session_commit" in issue for issue in report.issues)
    with pytest.raises(ValueError, match="missing session completion markers"):
        replay_targets_persistently(data, targets, config, path, reset=False)


def test_standalone_credit_after_latest_nav_is_not_falsely_marked_corrupt(tmp_path):
    data, config, targets, path = _prefix(tmp_path)
    day = data.close.index[25]
    with PaperLedger(path, base_currency="USD") as ledger:
        credit = ledger.accrue_cash_interest(day)
        assert credit > 0.0
        report = ledger.audit_integrity()
        assert report.is_valid
        assert report.nav_sessions == 6
        assert report.cash_credits == 6

    resumed = replay_targets_persistently(data, targets, config, path, reset=False)
    clean = replay_targets_persistently(
        data, targets, config, tmp_path / "clean.sqlite"
    )
    try:
        assert resumed.nav_history().equals(clean.nav_history())
        assert resumed.audit_integrity().is_valid
    finally:
        resumed.close()
        clean.close()


def test_direct_mark_without_atomic_checkpoint_is_reported_as_incomplete(tmp_path):
    data, config, _ = _case()
    path = tmp_path / "manual.sqlite"
    with PaperLedger(path, config.initial_cash, "USD") as ledger:
        day = data.close.index[19]
        ledger.mark_close(day, data.close.loc[day])
        report = ledger.audit_integrity()
        assert not report.is_valid
        assert any("missing_session_commit" in issue for issue in report.issues)


def test_coordinated_historical_cash_and_pnl_changes_fail_before_resume(tmp_path):
    data, config, targets, path = _prefix(tmp_path)
    day = data.close.index[21].isoformat()
    with sqlite3.connect(path) as db:
        # These fields agree with each other, but not with the posted cash flows.
        db.execute(
            "UPDATE nav SET cash=cash+37, equity=equity+37, "
            "realized_pnl=realized_pnl+37 WHERE timestamp=?",
            (day,),
        )
    with PaperLedger(path, base_currency="USD") as ledger:
        report = ledger.audit_integrity()
        assert any("nav_cashflow_mismatch" in issue for issue in report.issues)
        before = ledger.session_commits()

    with pytest.raises(ValueError, match="accounting integrity audit failed before replay"):
        replay_targets_persistently(data, targets, config, path, reset=False)
    with PaperLedger(path, base_currency="USD") as ledger:
        assert ledger.session_commits().equals(before)


@pytest.mark.parametrize(
    ("assignment", "issue"),
    [
        ("previous_close='2000-01-01T00:00:00'", "cash_interest_previous_close_mismatch"),
        ("eligible_cash_base=eligible_cash_base+2", "cash_interest_eligible_cash_mismatch"),
        ("annual_yield=annual_yield+0.0000001", "cash_interest_rate_mismatch"),
        ("accrual_days=accrual_days+1", "cash_interest_interval_mismatch"),
        ("interest_base=interest_base+2", "cash_interest_formula_mismatch"),
        ("cash_after_base=cash_after_base+2", "cash_interest_cash_after_mismatch"),
    ],
)
def test_credit_details_are_independently_verified(tmp_path, assignment, issue):
    data, config, targets, path = _prefix(tmp_path)
    stamp = data.close.index[22].isoformat()
    with sqlite3.connect(path) as db:
        db.execute(
            f"UPDATE cash_interest_credits SET {assignment} WHERE timestamp=?", (stamp,)
        )
    with PaperLedger(path, base_currency="USD") as ledger:
        assert any(issue in item for item in ledger.audit_integrity().issues)
    with pytest.raises(ValueError, match="accounting integrity audit failed before replay"):
        replay_targets_persistently(data, targets, config, path, reset=False)


def test_coordinated_interest_forgery_still_fails_the_formula_check(tmp_path):
    data, config, targets, path = _prefix(tmp_path)
    stamp = data.close.index[24].isoformat()
    with PaperLedger(path, base_currency="USD") as ledger:
        forged_cash = ledger.cash + 10.0
        ledger.connection.execute(
            "UPDATE cash_interest_credits SET interest_base=interest_base+10, "
            "cash_after_base=cash_after_base+10 WHERE timestamp=?", (stamp,)
        )
        ledger.connection.execute(
            "UPDATE nav SET cash=cash+10, equity=equity+10, "
            "cash_interest=cash_interest+10, cumulative_cash_interest=cumulative_cash_interest+10, "
            "realized_pnl=realized_pnl+10 WHERE timestamp=?", (stamp,)
        )
        ledger.connection.execute(
            "UPDATE metadata SET value=? WHERE key='cash'", (json.dumps(forged_cash),)
        )
        ledger.connection.commit()
        report = ledger.audit_integrity()
        assert any("cash_interest_formula_mismatch" in issue for issue in report.issues)
        assert not any("nav_cashflow_mismatch" in issue for issue in report.issues)
        assert not any("nav_pnl_mismatch" in issue for issue in report.issues)
    with pytest.raises(ValueError, match="accounting integrity audit failed before replay"):
        replay_targets_persistently(data, targets, config, path, reset=False)


def test_missing_zero_yield_credit_cannot_hide_behind_zero_nav_values(tmp_path):
    data, config, targets = _case()
    config = replace(config, cash_annual_yield=0.0)
    path = tmp_path / "zero-yield.sqlite"
    first = replay_targets_persistently(data.slice(end=data.close.index[24]), targets, config, path)
    first.close()
    stamp = data.close.index[22].isoformat()
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM cash_interest_credits WHERE timestamp=?", (stamp,))
    with PaperLedger(path, base_currency="USD") as ledger:
        assert any("missing_cash_interest_credit" in item for item in ledger.audit_integrity().issues)
    with pytest.raises(ValueError, match="accounting integrity audit failed before replay"):
        replay_targets_persistently(data, targets, config, path, reset=False)


@pytest.mark.parametrize("column", ["fill_price", "reference_price"])
def test_fill_prices_must_match_recorded_gross_and_slippage(tmp_path, column):
    data, config, targets, path = _prefix(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute(f"UPDATE fills SET {column}={column}+1")
    with PaperLedger(path, base_currency="USD") as ledger:
        assert any("fill_price_accounting_mismatch" in item for item in ledger.audit_integrity().issues)
    with pytest.raises(ValueError, match="accounting integrity audit failed before replay"):
        replay_targets_persistently(data, targets, config, path, reset=False)


def _mixed_cashflow_case():
    dates = pd.bdate_range("2026-01-02", periods=12)
    prices = pd.DataFrame({"AAA": 100.0, "BBB": 80.0}, index=dates)
    prices.loc[dates[4]:, "AAA"] = 200.0
    splits = pd.DataFrame(0.0, index=dates, columns=prices.columns)
    splits.loc[dates[4], "AAA"] = 0.5
    dividends = pd.DataFrame(0.0, index=dates, columns=prices.columns)
    dividends.loc[dates[5], "AAA"] = 2.0
    terminal = pd.DataFrame(float("nan"), index=dates, columns=prices.columns)
    terminal.loc[dates[7], "BBB"] = -0.4
    settlement_prices = pd.DataFrame(float("nan"), index=dates, columns=prices.columns)
    settlement_prices.loc[dates[6], "AAA"] = 205.0
    settlement_dates = pd.DataFrame(pd.NaT, index=dates, columns=prices.columns)
    settlement_dates.loc[dates[4], "AAA"] = dates[6]
    data = MarketData(
        open=prices,
        close=prices,
        volume=pd.DataFrame(100_000.0, index=dates, columns=prices.columns),
        stock_splits=splits,
        dividends=dividends,
        terminal_returns=terminal,
        cash_in_lieu_prices=settlement_prices,
        cash_in_lieu_settlement_dates=settlement_dates,
    )
    config = BacktestConfig(
        initial_cash=10_000.0,
        base_currency="USD",
        execution_price_basis="raw",
        cash_annual_yield=0.05,
        dividend_withholding=DividendWithholdingConfig(us_rate=0.3),
        us_costs=MarketCostConfig(
            commission_bps=10.0,
            sec_fee_per_million=20.6,
            slippage_bps=5.0,
            impact_coefficient=0.0,
            max_participation=1.0,
            lot_size=1,
        ),
    )
    targets = pd.DataFrame(
        [{"AAA": 0.11, "BBB": 0.08}, {"AAA": 0.0, "BBB": 0.0}],
        index=[dates[1], dates[8]],
    )
    return data, config, targets


def test_cash_reconstruction_accepts_buys_sells_tax_settlement_and_terminal(tmp_path):
    data, config, targets = _mixed_cashflow_case()
    ledger = replay_targets_persistently(data, targets, config, tmp_path / "mixed.sqlite")
    try:
        assert ledger.audit_integrity().is_valid
        fills = ledger.fills()
        assert set(fills["side"]) == {"BUY", "SELL"}
        actions = ledger.corporate_actions()
        assert set(actions["action"]) == {
            "stock_split", "cash_dividend", "cash_in_lieu_settlement"
        }
        nav = ledger.nav_history()
        dates = data.close.index
        for index, action in [(4, "stock_split"), (5, "cash_dividend"),
                              (6, "cash_in_lieu_settlement")]:
            event = actions.loc[actions["action"] == action].iloc[0]
            expected = nav.loc[dates[index - 1], "cash"] + nav.loc[dates[index], "cash_interest"]
            expected += event["cash_value"]
            assert nav.loc[dates[index], "cash"] == pytest.approx(expected)
        assert actions.loc[actions["action"] == "stock_split", "cash_value"].iloc[0] == 0
        assert ledger.cash_in_lieu_receivables().iloc[0]["status"] == "SETTLED"
        terminal = ledger.connection.execute("SELECT proceeds FROM terminal_events").fetchone()
        assert terminal is not None
        assert nav.loc[dates[7], "cash"] == pytest.approx(
            nav.loc[dates[6], "cash"] + nav.loc[dates[7], "cash_interest"] + terminal["proceeds"]
        )
    finally:
        ledger.close()


def test_corporate_action_tax_or_fx_corruption_fails_replay(tmp_path):
    data, config, targets = _mixed_cashflow_case()
    path = tmp_path / "mixed.sqlite"
    first = replay_targets_persistently(data.slice(end=data.close.index[7]), targets, config, path)
    first.close()
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE corporate_actions SET gross_cash_value=gross_cash_value+1, "
            "gross_cash_value_local=gross_cash_value_local+1 WHERE action='cash_dividend'"
        )
    with PaperLedger(path, base_currency="USD") as ledger:
        assert any("corporate_action_cashflow_mismatch" in item for item in ledger.audit_integrity().issues)
        before = ledger.session_commits()
    with pytest.raises(ValueError, match="accounting integrity audit failed before replay"):
        replay_targets_persistently(data, targets, config, path, reset=False)
    with PaperLedger(path, base_currency="USD") as ledger:
        assert ledger.session_commits().equals(before)


@pytest.mark.parametrize(
    ("action", "column", "issue"),
    [
        ("cash_dividend", "ratio_or_amount", "dividend_gross_mismatch"),
        ("cash_in_lieu_settlement", "cash_in_lieu_price", "cash_in_lieu_cashflow_mismatch"),
    ],
)
def test_corporate_cash_must_match_the_declared_amount_or_settlement_price(
    tmp_path, action, column, issue
):
    data, config, targets = _mixed_cashflow_case()
    path = tmp_path / "action.sqlite"
    ledger = replay_targets_persistently(data, targets, config, path)
    ledger.close()
    with sqlite3.connect(path) as db:
        db.execute(
            f"UPDATE corporate_actions SET {column}={column}+1 WHERE action=?", (action,)
        )
    with PaperLedger(path, base_currency="USD") as ledger:
        assert any(issue in item for item in ledger.audit_integrity().issues)


def test_cross_currency_cashflow_and_terminal_pass_audit(tmp_path):
    data, config, targets = _mixed_cashflow_case()
    prices = data.close.copy()
    prices["AAA"] *= 31.3
    dividends = data.dividends.copy()
    dividends["AAA"] *= 31.3
    settlements = data.cash_in_lieu_prices.copy()
    settlements["AAA"] *= 31.3
    currencies = pd.DataFrame({"AAA": "TWD", "BBB": "USD"}, index=data.close.index)
    data = attach_fx_rates(
        replace(
            data,
            open=prices,
            close=prices,
            raw_open=prices,
            raw_close=prices,
            reference=prices.shift(1),
            dividends=dividends,
            cash_in_lieu_prices=settlements,
            currency_codes=currencies,
        ),
        "USD",
        pd.Series(31.3, index=data.close.index),
    )
    ledger = replay_targets_persistently(data, targets, config, tmp_path / "foreign.sqlite")
    try:
        assert ledger.audit_integrity().is_valid
        foreign = ledger.fills().query("symbol == 'AAA'").iloc[0]
        assert foreign["local_currency"] == "TWD"
        assert foreign["fx_to_base"] == pytest.approx(1 / 31.3)
        assert foreign["gross_value"] == pytest.approx(
            foreign["gross_value_local"] / 31.3
        )
        actions = ledger.corporate_actions()
        foreign_actions = actions[actions["action"].isin(["cash_dividend", "cash_in_lieu_settlement"])]
        assert set(foreign_actions["action"]) == {"cash_dividend", "cash_in_lieu_settlement"}
        assert foreign_actions["local_currency"].eq("TWD").all()
        assert foreign_actions["cash_value"].to_numpy() == pytest.approx(
            foreign_actions["cash_value_local"].to_numpy() / 31.3
        )
        assert ledger.connection.execute("SELECT COUNT(*) FROM terminal_events").fetchone()[0] == 1
    finally:
        ledger.close()


def test_corrupt_pending_receivable_cannot_advance_replay(tmp_path):
    data, config, targets = _mixed_cashflow_case()
    path = tmp_path / "pending.sqlite"
    prefix = replay_targets_persistently(data.slice(end=data.close.index[4]), targets, config, path)
    try:
        assert prefix.cash_in_lieu_receivables().iloc[0]["status"] == "OPEN"
        assert prefix.audit_integrity().is_valid
        before = prefix.session_commits()
        prefix.connection.execute("UPDATE cash_in_lieu_receivables SET status='SETTLED'")
        prefix.connection.commit()
        assert any("invalid_receivable_state" in item for item in prefix.audit_integrity().issues)
    finally:
        prefix.close()

    with pytest.raises(ValueError, match="accounting integrity audit failed before replay"):
        replay_targets_persistently(data, targets, config, path, reset=False)
    with PaperLedger(path, base_currency="USD") as ledger:
        assert ledger.session_commits().equals(before)


def test_open_receivable_resumes_identically_to_uninterrupted_replay(tmp_path):
    data, config, targets = _mixed_cashflow_case()
    path = tmp_path / "resume-receivable.sqlite"
    prefix = replay_targets_persistently(data.slice(end=data.close.index[4]), targets, config, path)
    try:
        assert prefix.cash_in_lieu_receivables().iloc[0]["status"] == "OPEN"
        assert prefix.audit_integrity().is_valid
    finally:
        prefix.close()
    resumed = replay_targets_persistently(data, targets, config, path, reset=False)
    clean = replay_targets_persistently(data, targets, config, tmp_path / "clean-receivable.sqlite")
    try:
        assert resumed.audit_integrity().is_valid
        assert resumed.nav_history().equals(clean.nav_history())
        assert resumed.corporate_actions().equals(clean.corporate_actions())
        assert resumed.cash_in_lieu_receivables().equals(clean.cash_in_lieu_receivables())
    finally:
        resumed.close()
        clean.close()


def test_nanosecond_session_timestamps_remain_valid(tmp_path):
    data, config, targets = _mixed_cashflow_case()
    offset = pd.Timedelta(nanoseconds=123_456_789)
    index = data.close.index + offset
    names = (
        "open", "close", "volume", "raw_open", "raw_close", "reference",
        "membership", "terminal_returns", "dividends", "stock_splits",
        "cash_in_lieu_prices", "cash_in_lieu_settlement_dates",
    )
    frames = {name: getattr(data, name).set_axis(index, axis=0) for name in names}
    frames["cash_in_lieu_settlement_dates"].loc[index[4], "AAA"] = index[6]
    data = replace(data, **frames)
    targets = targets.set_axis(targets.index + offset, axis=0)
    ledger = replay_targets_persistently(data, targets, config, tmp_path / "nanoseconds.sqlite")
    try:
        assert ledger.audit_integrity().is_valid
        assert ledger.cash_in_lieu_receivables().iloc[0]["status"] == "SETTLED"
    finally:
        ledger.close()


@pytest.mark.parametrize(
    ("assignment", "issue"),
    [
        ("status='OPEN'", "invalid_receivable_state"),
        ("cash_value=cash_value+1", "receivable_settlement_cashflow_mismatch"),
        ("realized_pnl_delta=realized_pnl_delta+1", "receivable_settlement_cashflow_mismatch"),
    ],
)
def test_settled_receivable_details_must_match_cashflow_and_event(tmp_path, assignment, issue):
    data, config, targets = _mixed_cashflow_case()
    path = tmp_path / "settled.sqlite"
    prefix = replay_targets_persistently(data.slice(end=data.close.index[7]), targets, config, path)
    prefix.close()
    with sqlite3.connect(path) as db:
        db.execute(f"UPDATE cash_in_lieu_receivables SET {assignment}")
    with PaperLedger(path, base_currency="USD") as ledger:
        assert any(issue in item for item in ledger.audit_integrity().issues)
        before = ledger.session_commits()
    with pytest.raises(ValueError, match="accounting integrity audit failed before replay"):
        replay_targets_persistently(data, targets, config, path, reset=False)
    with PaperLedger(path, base_currency="USD") as ledger:
        assert ledger.session_commits().equals(before)


def test_multiple_receivables_with_same_settlement_date_match_individually(tmp_path):
    data, config, targets = _mixed_cashflow_case()
    dates = data.close.index
    prices = data.close.copy()
    prices.loc[dates[5]:, "AAA"] *= 2
    splits = data.stock_splits.copy()
    splits.loc[dates[5], "AAA"] = 0.5
    settlement_dates = data.cash_in_lieu_settlement_dates.copy()
    settlement_dates.loc[dates[5], "AAA"] = dates[6]
    data = replace(
        data,
        open=prices,
        close=prices,
        raw_open=prices,
        raw_close=prices,
        stock_splits=splits,
        cash_in_lieu_settlement_dates=settlement_dates,
    )
    ledger = replay_targets_persistently(data, targets, config, tmp_path / "multiple.sqlite")
    try:
        receivables = ledger.cash_in_lieu_receivables()
        assert len(receivables) == 2
        assert receivables["status"].eq("SETTLED").all()
        assert len(ledger.corporate_actions().query("action == 'cash_in_lieu_settlement'")) == 2
        assert ledger.audit_integrity().is_valid
    finally:
        ledger.close()


def test_large_portfolio_rounding_does_not_create_spurious_pnl_issues(tmp_path):
    dates = pd.bdate_range("2025-01-01", periods=45)
    rng = np.random.default_rng(0)
    prices = pd.DataFrame(
        100 * np.exp(np.cumsum(rng.normal(0, 0.005, (45, 4)), axis=0)),
        index=dates,
        columns=["AAA", "BBB", "CCC", "DDD"],
    )
    data = MarketData(open=prices * 1.001, close=prices, volume=prices * 1e17)
    targets = pd.DataFrame(
        [rng.dirichlet(np.ones(4)) * weight for weight in (0.99, 0.7, 0.95, 0.1)],
        index=dates[[1, 10, 20, 30]],
        columns=prices.columns,
    )
    config = BacktestConfig(
        initial_cash=1e12,
        base_currency="USD",
        cash_annual_yield=0.05,
        us_costs=MarketCostConfig(
            commission_bps=10,
            sec_fee_per_million=20.6,
            slippage_bps=3,
            impact_coefficient=0.1,
            max_participation=1.0,
        ),
    )
    ledger = replay_targets_persistently(data, targets, config, tmp_path / "large.sqlite")
    try:
        assert ledger.audit_integrity().is_valid
    finally:
        ledger.close()


def test_uncommitted_trading_outside_the_supplied_dates_is_not_ignored(tmp_path):
    data, config, targets, path = _prefix(tmp_path)
    future = (data.close.index[-1] + pd.Timedelta(days=10)).isoformat()
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO terminal_events(timestamp, symbol, quantity, reference_price, "
            "terminal_return, proceeds, realized_pnl_base) VALUES(?, 'AAA', 1, 100, -1, 0, 0)",
            (future,),
        )
    with PaperLedger(path, base_currency="USD") as ledger:
        assert any("incomplete persistent session" in item for item in ledger.audit_integrity().issues)
        before = ledger.session_commits()
    with pytest.raises(ValueError, match="incomplete persistent session"):
        replay_targets_persistently(data, targets, config, path, reset=False)
    with PaperLedger(path, base_currency="USD") as ledger:
        assert ledger.session_commits().equals(before)


def test_stranded_zero_interest_credit_rejects_before_any_new_session(tmp_path):
    data, config, targets = _case()
    config = replace(config, cash_annual_yield=0.0)
    path = tmp_path / "stranded-credit.sqlite"
    prefix = replay_targets_persistently(data.slice(end=data.close.index[24]), targets, config, path)
    try:
        # A zero credit can be posted for a future day without changing cash.
        prefix.accrue_cash_interest(data.close.index[26])
        before = prefix.session_commits()
        assert prefix.audit_integrity().is_valid
    finally:
        prefix.close()
    with pytest.raises(ValueError, match="credit must match the next replay session"):
        replay_targets_persistently(data, targets, config, path, reset=False)
    with PaperLedger(path, base_currency="USD") as ledger:
        assert ledger.session_commits().equals(before)


def test_unordered_sessions_are_rejected_before_existing_ledger_is_touched(tmp_path):
    data, config, targets = _case()
    unordered = MarketData(
        open=data.open.iloc[::-1],
        close=data.close.iloc[::-1],
        volume=data.volume.iloc[::-1],
    )
    path = tmp_path / "existing.sqlite"
    path.write_bytes(b"existing ledger sentinel")
    with pytest.raises(ValueError, match="sessions in chronological order"):
        replay_targets_persistently(unordered, targets, config, path, reset=True)
    assert path.read_bytes() == b"existing ledger sentinel"
