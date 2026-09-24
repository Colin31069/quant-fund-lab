"""M11-4: lock exact replay data seen by every completed persistent session."""

import sqlite3
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.paper_live import PaperLedger, replay_targets_persistently
from quant_fund_lab.replay_provenance import replay_session_data_fingerprint


def _case():
    data = synthetic_market_data(symbols=("AAA", "BBB"), periods=38, seed=55)
    ones = pd.DataFrame(1.0, index=data.close.index, columns=data.symbols)
    zeros = pd.DataFrame(0.0, index=data.close.index, columns=data.symbols)
    data = replace(
        data,
        fx_to_base=ones,
        fx_age_days=zeros,
        base_currency="USD",
        cash_in_lieu_prices=pd.DataFrame(np.nan, index=data.close.index, columns=data.symbols),
        cash_in_lieu_settlement_dates=pd.DataFrame(
            pd.NaT, index=data.close.index, columns=data.symbols
        ),
    )
    config = BacktestConfig(
        initial_cash=100_000.0,
        base_currency="USD",
        cash_annual_yield=0.05,
        strategy=StrategyConfig(warmup_days=20),
    )
    targets = pd.DataFrame(
        [{"AAA": 0.20, "BBB": 0.0}], index=[data.close.index[19]]
    )
    return data, config, targets


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("open", 50.0),
        ("close", 50.0),
        ("volume", 987_654),
        ("raw_open", 51.0),
        ("raw_close", 52.0),
        ("reference", 53.0),
        ("membership", False),
        ("terminal_returns", -0.10),
        ("dividends", 0.75),
        ("stock_splits", 1.5),
        ("cash_in_lieu_prices", 50.0),
        ("cash_in_lieu_settlement_dates", pd.Timestamp("2024-05-01")),
        ("fx_to_base", 1.10),
        ("fx_age_days", 2.0),
        ("market_codes", "TW"),
        ("currency_codes", "TWD"),
    ],
)
def test_changed_completed_market_inputs_fail_before_new_trades(
    tmp_path, field, replacement
):
    data, config, targets = _case()
    path = tmp_path / "unchanged-history.sqlite"
    prefix = replay_targets_persistently(
        data.slice(end=data.close.index[24]), targets, config, path
    )
    try:
        before_nav = prefix.nav_history()
        before_fills = prefix.fills()
        before_orders = prefix.orders()
        before_interest = prefix.cash_interest_credits()
        before_commits = prefix.session_commits()
        before_cash = prefix.cash
    finally:
        prefix.close()

    day = data.close.index[22]
    frame = getattr(data, field).copy()
    frame.at[day, "AAA"] = replacement
    revised = replace(data, **{field: frame})
    with pytest.raises(ValueError, match=rf"replay data fingerprint mismatch on {day.date()}"):
        replay_targets_persistently(revised, targets, config, path, reset=False)

    with PaperLedger(path, base_currency="USD") as ledger:
        assert ledger.nav_history().equals(before_nav)
        assert ledger.fills().equals(before_fills)
        assert ledger.orders().equals(before_orders)
        assert ledger.cash_interest_credits().equals(before_interest)
        assert ledger.session_commits().equals(before_commits)
        assert ledger.cash == pytest.approx(before_cash)


def test_completed_market_inputs_remain_locked_even_on_noop_replay(tmp_path):
    data, config, targets = _case()
    path = tmp_path / "noop-history.sqlite"
    complete = replay_targets_persistently(data, targets, config, path)
    try:
        earlier = complete.session_commits()
        assert earlier["data_fingerprint"].str.fullmatch("[0-9a-f]{64}").all()
    finally:
        complete.close()

    changed_close = data.close.copy()
    changed_close.at[data.close.index[21], "BBB"] += 1.0
    changed = replace(data, close=changed_close)
    with pytest.raises(ValueError, match="replay data fingerprint mismatch"):
        replay_targets_persistently(changed, targets, config, path, reset=False)


def test_unchanged_full_history_can_resume_and_reproduce_fingerprints(tmp_path):
    data, config, targets = _case()
    path = tmp_path / "resume.sqlite"
    first = replay_targets_persistently(
        data.slice(end=data.close.index[24]), targets, config, path
    )
    try:
        first_commits = first.session_commits()
        first_nav = first.nav_history()
    finally:
        first.close()

    full = replay_targets_persistently(data, targets, config, path, reset=False)
    clean = replay_targets_persistently(data, targets, config, tmp_path / "clean.sqlite")
    try:
        assert full.session_commits().equals(clean.session_commits())
        assert full.nav_history().equals(clean.nav_history())
        assert full.session_commits().loc[first_commits.index].equals(first_commits)
        assert full.nav_history().loc[first_nav.index].equals(first_nav)
    finally:
        full.close()
        clean.close()


def test_missing_earlier_data_cannot_bypass_provenance_verification(tmp_path):
    data, config, targets = _case()
    path = tmp_path / "missing-history.sqlite"
    first = replay_targets_persistently(
        data.slice(end=data.close.index[24]), targets, config, path
    )
    try:
        initial_marks = first.nav_history()
        initial_commits = first.session_commits()
    finally:
        first.close()

    suffix_only = data.slice(start=data.close.index[22])
    with pytest.raises(ValueError, match="missing completed sessions required for provenance"):
        replay_targets_persistently(suffix_only, targets, config, path, reset=False)
    with PaperLedger(path, base_currency="USD") as ledger:
        assert ledger.nav_history().equals(initial_marks)
        assert ledger.session_commits().equals(initial_commits)


def test_benchmark_changes_or_missing_benchmark_fail_before_replay(tmp_path):
    data, config, targets = _case()
    benchmark = pd.Series(
        100.0 + np.arange(len(data.close)), index=data.close.index
    )
    path = tmp_path / "benchmark.sqlite"
    prefix = replay_targets_persistently(
        data.slice(end=data.close.index[24]),
        targets,
        config,
        path,
        benchmark_close_base=benchmark,
    )
    prefix.close()
    modified = benchmark.copy()
    modified.at[data.close.index[21]] += 0.5
    with pytest.raises(ValueError, match="replay data fingerprint mismatch"):
        replay_targets_persistently(
            data,
            targets,
            config,
            path,
            benchmark_close_base=modified,
            reset=False,
        )
    with pytest.raises(ValueError, match="replay data fingerprint mismatch"):
        replay_targets_persistently(data, targets, config, path, reset=False)


def test_m11_3_legacy_completion_rows_migrate_but_fail_closed(tmp_path):
    data, config, targets = _case()
    path = tmp_path / "legacy-session-commits.sqlite"
    first = replay_targets_persistently(
        data.slice(end=data.close.index[24]), targets, config, path
    )
    try:
        prior_nav = first.nav_history()
        assert not first.session_commits().empty
    finally:
        first.close()

    # Re-create the historical M11-3 table schema to test an actual ALTER migration.
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            ALTER TABLE session_commits RENAME TO old_session_commits;
            CREATE TABLE session_commits (
                timestamp TEXT PRIMARY KEY REFERENCES nav(timestamp),
                had_signal INTEGER NOT NULL CHECK(had_signal IN (0, 1)),
                signal_fingerprint TEXT NOT NULL,
                snapshot_dataset_id TEXT
            );
            INSERT INTO session_commits (
                timestamp, had_signal, signal_fingerprint, snapshot_dataset_id
            )
            SELECT timestamp, had_signal, signal_fingerprint, snapshot_dataset_id
            FROM old_session_commits;
            DROP TABLE old_session_commits;
            """
        )

    with PaperLedger(path, base_currency="USD") as migrated:
        assert migrated.session_commits()["data_fingerprint"].eq("").all()
        assert migrated.nav_history().equals(prior_nav)
    with pytest.raises(ValueError, match="legacy paper ledger has no replay data fingerprint"):
        replay_targets_persistently(data, targets, config, path, reset=False)


def test_new_future_data_can_change_without_rewriting_completed_history(tmp_path):
    data, config, targets = _case()
    path = tmp_path / "future-only.sqlite"
    prefix = replay_targets_persistently(
        data.slice(end=data.close.index[24]), targets, config, path
    )
    try:
        prior_commits = prefix.session_commits()
    finally:
        prefix.close()

    future = data.raw_close.copy()
    future.at[data.close.index[27], "AAA"] *= 1.01
    revised = replace(data, raw_close=future)
    continued = replay_targets_persistently(revised, targets, config, path, reset=False)
    try:
        commits = continued.session_commits()
        assert commits.loc[prior_commits.index].equals(prior_commits)
        assert commits.loc[data.close.index[27], "data_fingerprint"] != (
            replay_session_data_fingerprint(
                data,
                data.close.index[27],
                data.reference.loc[data.close.index[27]],
                None,
            )
        )
    finally:
        continued.close()


def test_data_fingerprint_stable_across_identical_frame_copies():
    data, _, _ = _case()
    day = data.close.index[21]
    before = replay_session_data_fingerprint(data, day, data.reference.loc[day], None)
    copied = replace(data, close=data.close.copy(), fx_to_base=data.fx_to_base.copy())
    after = replay_session_data_fingerprint(copied, day, copied.reference.loc[day], None)
    assert before == after
    assert len(before) == 64
