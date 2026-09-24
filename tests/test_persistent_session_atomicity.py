from dataclasses import replace

import pandas as pd
import pytest

from quant_fund_lab.config import BacktestConfig, MarketCostConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.paper_live import PaperLedger, replay_targets_persistently


def _trading_case():
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
    return data, config, targets


def test_fail_after_nav_before_signal_rolls_back_entire_first_session(
    tmp_path, monkeypatch
):
    data, config, targets = _trading_case()
    path = tmp_path / "atomic-first.sqlite"
    snapshots = tmp_path / "snapshots"
    def fail_after_nav(self, *args, **kwargs):
        assert self.connection.execute("SELECT COUNT(*) FROM nav").fetchone()[0] == 1
        assert self.connection.execute(
            "SELECT COUNT(*) FROM snapshots"
        ).fetchone()[0] == 1
        raise RuntimeError("injected failure after NAV and snapshot, before orders")

    with monkeypatch.context() as patch:
        patch.setattr(PaperLedger, "submit_target_orders", fail_after_nav)
        with pytest.raises(RuntimeError, match="injected failure"):
            replay_targets_persistently(
                data, targets, config, path, snapshot_root=snapshots
            )

    # The filesystem snapshot is not a SQLite row; an orphan is safely overwritten.
    assert (snapshots / data.close.index[19].strftime("%Y-%m-%d")).exists()
    with PaperLedger(path, base_currency="USD") as ledger:
        assert ledger.nav_history().empty
        assert ledger.orders().empty
        assert ledger.fills().empty
        assert ledger.snapshots().empty
        assert ledger.cash_interest_credits().empty
        assert ledger.session_commits().empty
        assert ledger.cash == pytest.approx(config.initial_cash)
        ledger.ensure_cash_annual_yield(config.cash_annual_yield)

    baseline = replay_targets_persistently(
        data, targets, config, tmp_path / "baseline.sqlite", snapshot_root=tmp_path / "base-snap"
    )
    retried = replay_targets_persistently(
        data, targets, config, path, snapshot_root=snapshots, reset=False
    )
    try:
        assert retried.orders().equals(baseline.orders())
        assert retried.fills().equals(baseline.fills())
        assert retried.nav_history().equals(baseline.nav_history())
        assert len(retried.session_commits()) == len(retried.nav_history())
        assert len(retried.snapshots()) == len(retried.nav_history())
        assert set(retried.session_commits()["snapshot_dataset_id"]) == set(
            retried.snapshots()["dataset_id"]
        )
    finally:
        retried.close()
        baseline.close()


def test_failed_session_after_fills_rolls_back_fill_interest_nav_and_marker(
    tmp_path, monkeypatch
):
    data, config, targets = _trading_case()
    path = tmp_path / "mid-session.sqlite"
    first_day, fill_day = data.close.index[19:21]
    prefix = replay_targets_persistently(
        data.slice(end=first_day), targets, config, path
    )
    try:
        original_orders = prefix.orders()
        assert original_orders.iloc[0]["status"] == "NEW"
    finally:
        prefix.close()

    original_mark = PaperLedger.mark_close

    def fail_after_mark(self, timestamp, *args, **kwargs):
        result = original_mark(self, timestamp, *args, **kwargs)
        if pd.Timestamp(timestamp) == fill_day:
            assert len(self.fills()) == 1
            assert result["cash_interest"] > 0
            raise RuntimeError("injected failure after fill and NAV")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(PaperLedger, "mark_close", fail_after_mark)
        with pytest.raises(RuntimeError, match="injected failure"):
            replay_targets_persistently(data, targets, config, path, reset=False)

    with PaperLedger(path, base_currency="USD") as ledger:
        assert ledger.orders().equals(original_orders)
        assert ledger.fills().empty
        assert ledger.nav_history().index.tolist() == [first_day]
        assert ledger.cash_interest_credits().empty
        assert ledger.session_commits().index.tolist() == [first_day]
        assert ledger.positions().empty
        assert ledger.cash == pytest.approx(config.initial_cash)

    completed = replay_targets_persistently(data, targets, config, path, reset=False)
    clean = replay_targets_persistently(data, targets, config, tmp_path / "clean.sqlite")
    try:
        assert len(completed.fills()) == 1
        assert completed.fills().equals(clean.fills())
        assert completed.orders().equals(clean.orders())
        assert completed.nav_history().equals(clean.nav_history())
        assert completed.session_commits().equals(clean.session_commits())
        assert completed.nav_history()["reconciliation_error"].abs().max() < 1e-8
    finally:
        completed.close()
        clean.close()


def test_failure_after_order_insert_rolls_back_checkpoint_and_orders(
    tmp_path, monkeypatch
):
    data, config, targets = _trading_case()
    path = tmp_path / "after-order.sqlite"
    original_record = PaperLedger.record_session_commit

    def fail_after_marker(self, *args, **kwargs):
        original_record(self, *args, **kwargs)
        assert len(self.orders()) == 1
        assert len(self.session_commits()) == 1
        raise RuntimeError("injected failure after checkpoint")

    with monkeypatch.context() as patch:
        patch.setattr(PaperLedger, "record_session_commit", fail_after_marker)
        with pytest.raises(RuntimeError, match="injected failure"):
            replay_targets_persistently(data, targets, config, path)

    with PaperLedger(path, base_currency="USD") as ledger:
        assert ledger.orders().empty
        assert ledger.nav_history().empty
        assert ledger.session_commits().empty


def test_legacy_nav_without_atomic_checkpoint_fails_closed(tmp_path):
    data, config, targets = _trading_case()
    path = tmp_path / "legacy-nav.sqlite"
    day = data.close.index[19]
    with PaperLedger(path, config.initial_cash, "USD") as ledger:
        ledger.mark_close(day, data.close.loc[day])
        assert len(ledger.nav_history()) == 1
        assert ledger.session_commits().empty

    with pytest.raises(ValueError, match="session completion markers"):
        replay_targets_persistently(
            data, targets, replace(config, cash_annual_yield=0.0), path, reset=False
        )
    with PaperLedger(path, base_currency="USD") as ledger:
        assert len(ledger.nav_history()) == 1
        assert ledger.orders().empty


def test_changed_or_missing_completed_targets_cannot_silently_resume(tmp_path):
    data, config, targets = _trading_case()
    path = tmp_path / "signal-fingerprint.sqlite"
    prefix = replay_targets_persistently(
        data.slice(end=data.close.index[24]), targets, config, path
    )
    try:
        before_nav = prefix.nav_history()
        before_orders = prefix.orders()
    finally:
        prefix.close()

    changed = targets.copy()
    changed.iloc[0, 0] = 0.40
    with pytest.raises(ValueError, match="target weights conflict"):
        replay_targets_persistently(data, changed, config, path, reset=False)
    missing = pd.DataFrame(
        [{"AAA": 0.30, "BBB": 0.0}], index=[data.close.index[27]]
    )
    with pytest.raises(ValueError, match="target schedule conflicts"):
        replay_targets_persistently(data, missing, config, path, reset=False)
    added = pd.concat(
        [targets, pd.DataFrame([{"AAA": 0.0, "BBB": 0.0}], index=[data.close.index[21]])]
    )
    with pytest.raises(ValueError, match="target schedule conflicts"):
        replay_targets_persistently(data, added, config, path, reset=False)

    with PaperLedger(path, base_currency="USD") as ledger:
        assert ledger.nav_history().equals(before_nav)
        assert ledger.orders().equals(before_orders)


def test_initial_cash_and_duplicate_signal_dates_fail_before_replay(tmp_path):
    data, config, targets = _trading_case()
    dupe_path = tmp_path / "duplicates.sqlite"
    duplicate = pd.concat([targets, targets])
    with pytest.raises(ValueError, match="unique session and target timestamps"):
        replay_targets_persistently(data, duplicate, config, dupe_path)
    assert not dupe_path.exists()

    path = tmp_path / "funding-lock.sqlite"
    prefix = replay_targets_persistently(
        data.slice(end=data.close.index[24]), targets, config, path
    )
    prefix.close()
    with pytest.raises(ValueError, match="initial_cash does not match"):
        replay_targets_persistently(
            data, targets, replace(config, initial_cash=200_000.0), path, reset=False
        )


def test_repeating_a_fully_committed_replay_is_a_noop(tmp_path):
    data, config, targets = _trading_case()
    path = tmp_path / "no-op.sqlite"
    first = replay_targets_persistently(data, targets, config, path)
    try:
        prior_nav = first.nav_history()
        prior_orders = first.orders()
        prior_fills = first.fills()
        prior_credits = first.cash_interest_credits()
        prior_commits = first.session_commits()
    finally:
        first.close()

    second = replay_targets_persistently(data, targets, config, path, reset=False)
    try:
        assert second.nav_history().equals(prior_nav)
        assert second.orders().equals(prior_orders)
        assert second.fills().equals(prior_fills)
        assert second.cash_interest_credits().equals(prior_credits)
        assert second.session_commits().equals(prior_commits)
        assert len(prior_commits) == len(prior_nav)
    finally:
        second.close()


def test_atomic_raw_split_and_dividend_roll_back_together(tmp_path, monkeypatch):
    data, config, targets = _trading_case()
    split_day = data.close.index[21]
    raw_open, raw_close = data.open.copy(), data.close.copy()
    raw_open.loc[split_day:, "AAA"] *= 0.5
    raw_close.loc[split_day:, "AAA"] *= 0.5
    stock_splits = data.stock_splits.copy()
    dividends = data.dividends.copy()
    stock_splits.loc[split_day, "AAA"] = 2.0
    dividends.loc[split_day, "AAA"] = 0.25
    data = replace(
        data,
        raw_open=raw_open,
        raw_close=raw_close,
        stock_splits=stock_splits,
        dividends=dividends,
    )
    config = replace(config, execution_price_basis="raw")
    path = tmp_path / "raw-atomic.sqlite"
    prefix = replay_targets_persistently(
        data.slice(end=data.close.index[20]), targets, config, path
    )
    try:
        earlier_positions = prefix.positions()
        earlier_cash = prefix.cash
        earlier_nav = prefix.nav_history()
        assert not earlier_positions.empty
    finally:
        prefix.close()

    original_mark = PaperLedger.mark_close

    def fail_after_corporate_action_mark(self, timestamp, *args, **kwargs):
        result = original_mark(self, timestamp, *args, **kwargs)
        if pd.Timestamp(timestamp) == split_day:
            assert len(self.corporate_actions()) == 2
            assert result["cash_interest"] > 0.0
            raise RuntimeError("injected failure after raw actions and NAV")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(PaperLedger, "mark_close", fail_after_corporate_action_mark)
        with pytest.raises(RuntimeError, match="injected failure"):
            replay_targets_persistently(data, targets, config, path, reset=False)

    with PaperLedger(path, base_currency="USD") as ledger:
        assert ledger.positions().equals(earlier_positions)
        assert ledger.cash == pytest.approx(earlier_cash)
        assert ledger.corporate_actions().empty
        assert ledger.nav_history().equals(earlier_nav)
        assert len(ledger.session_commits()) == len(earlier_nav)
        assert len(ledger.cash_interest_credits()) == len(earlier_nav) - 1

    continued = replay_targets_persistently(data, targets, config, path, reset=False)
    clean = replay_targets_persistently(data, targets, config, tmp_path / "raw-clean.sqlite")
    try:
        assert len(continued.corporate_actions()) == 2
        assert continued.corporate_actions().equals(clean.corporate_actions())
        assert continued.positions().equals(clean.positions())
        assert continued.nav_history().equals(clean.nav_history())
        assert continued.nav_history()["reconciliation_error"].abs().max() < 1e-8
    finally:
        continued.close()
        clean.close()
