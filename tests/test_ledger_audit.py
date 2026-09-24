"""M11-7: independent read-only SQL ledger reconciliation and replay gate."""

import sqlite3

import pandas as pd
import pytest

from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data
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
