"""M11-5: persistent execution assumptions and committed snapshot linkage."""

import json
import sqlite3
from dataclasses import replace

import pandas as pd
import pytest

from quant_fund_lab.config import BacktestConfig, MarketCostConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.paper_live import PaperLedger, replay_targets_persistently
from quant_fund_lab.snapshot import load_market_data_snapshot, save_market_data_snapshot


def _case():
    data = synthetic_market_data(symbols=("AAA", "BBB"), periods=37, seed=63)
    config = BacktestConfig(
        initial_cash=100_000.0,
        base_currency="USD",
        cash_annual_yield=0.04,
        strategy=StrategyConfig(warmup_days=20),
        us_costs=MarketCostConfig(
            commission_bps=1.0,
            sell_tax_bps=0.0,
            sec_fee_per_million=20.6,
            slippage_bps=3.0,
            impact_coefficient=0.1,
            max_participation=0.5,
            lot_size=1,
        ),
    )
    targets = pd.DataFrame(
        [{"AAA": 0.25, "BBB": 0.0}], index=[data.close.index[19]]
    )
    return data, config, targets


@pytest.mark.parametrize(
    "changed_config",
    [
        lambda cfg: replace(
            cfg, us_costs=replace(cfg.us_costs, commission_bps=2.0)
        ),
        lambda cfg: replace(
            cfg, us_costs=replace(cfg.us_costs, slippage_bps=8.0)
        ),
        lambda cfg: replace(
            cfg, us_costs=replace(cfg.us_costs, impact_coefficient=0.25)
        ),
        lambda cfg: replace(
            cfg, us_costs=replace(cfg.us_costs, max_participation=0.15)
        ),
        lambda cfg: replace(
            cfg, tw_costs=replace(cfg.tw_costs, lot_size=100)
        ),
        lambda cfg: replace(cfg, max_fx_staleness_days=3),
        lambda cfg: replace(
            cfg, dividend_withholding=replace(cfg.dividend_withholding, us_rate=0.15)
        ),
    ],
    ids=[
        "commission", "slippage", "market-impact", "participation",
        "TW-lot", "FX-staleness", "dividend-tax",
    ],
)
def test_completed_ledger_locks_execution_assumptions_before_next_session(
    tmp_path, changed_config
):
    data, config, targets = _case()
    path = tmp_path / "locked-execution.sqlite"
    prefix = replay_targets_persistently(
        data.slice(end=data.close.index[24]), targets, config, path
    )
    try:
        existing_nav = prefix.nav_history()
        existing_orders = prefix.orders()
        existing_fills = prefix.fills()
        assert prefix._meta_value("replay_execution_config")["schema_version"] == 1
    finally:
        prefix.close()

    with pytest.raises(ValueError, match="execution config conflicts with locked ledger"):
        replay_targets_persistently(
            data, targets, changed_config(config), path, reset=False
        )
    with PaperLedger(path, base_currency="USD") as ledger:
        assert ledger.nav_history().equals(existing_nav)
        assert ledger.orders().equals(existing_orders)
        assert ledger.fills().equals(existing_fills)


def test_strategy_research_settings_can_change_when_signals_are_supplied(tmp_path):
    data, config, targets = _case()
    path = tmp_path / "strategy-independent.sqlite"
    first = replay_targets_persistently(
        data.slice(end=data.close.index[24]), targets, config, path
    )
    first.close()
    updated = replace(config, strategy=replace(config.strategy, rebalance_every=3))
    resumed = replay_targets_persistently(data, targets, updated, path, reset=False)
    clean = replay_targets_persistently(data, targets, config, tmp_path / "clean.sqlite")
    try:
        assert resumed.nav_history().equals(clean.nav_history())
        assert resumed.fills().equals(clean.fills())
    finally:
        resumed.close()
        clean.close()


def test_existing_sessions_without_execution_lock_fail_closed(tmp_path):
    data, config, targets = _case()
    path = tmp_path / "legacy-execution.sqlite"
    prefix = replay_targets_persistently(
        data.slice(end=data.close.index[24]), targets, config, path
    )
    try:
        prior_marks = prefix.nav_history()
    finally:
        prefix.close()
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM metadata WHERE key='replay_execution_config'")
    with pytest.raises(ValueError, match="lacks a replay execution config lock"):
        replay_targets_persistently(data, targets, config, path, reset=False)
    with PaperLedger(path, base_currency="USD") as ledger:
        assert ledger.nav_history().equals(prior_marks)
        assert ledger._meta_value("replay_execution_config") is None


def _snapshot_prefix(tmp_path):
    data, config, targets = _case()
    path = tmp_path / "snapshot-linked.sqlite"
    root = tmp_path / "snapshots"
    first = replay_targets_persistently(
        data.slice(end=data.close.index[22]),
        targets,
        config,
        path,
        snapshot_root=root,
    )
    try:
        old_nav = first.nav_history()
        old_snapshots = first.snapshots()
        old_commits = first.session_commits()
        assert len(old_snapshots) == len(old_nav)
    finally:
        first.close()
    return data, config, targets, path, root, old_nav, old_snapshots, old_commits


def test_snapshots_are_revalidated_and_linked_on_resume(tmp_path):
    data, config, targets, path, root, _, previous, _ = _snapshot_prefix(tmp_path)
    resumed = replay_targets_persistently(
        data, targets, config, path, snapshot_root=root, reset=False
    )
    clean = replay_targets_persistently(
        data, targets, config, tmp_path / "clean.sqlite",
        snapshot_root=tmp_path / "clean-snapshots",
    )
    try:
        assert resumed.nav_history().equals(clean.nav_history())
        assert resumed.session_commits().equals(clean.session_commits())
        assert len(resumed.snapshots()) == len(resumed.nav_history())
        assert resumed.snapshots().loc[: len(previous) - 1, "dataset_id"].tolist() == (
            previous["dataset_id"].tolist()
        )
    finally:
        resumed.close()
        clean.close()


@pytest.mark.parametrize("mode", ["missing-file", "corrupt-parquet", "manifest-id"])
def test_tampered_snapshot_fails_before_any_new_accounting(tmp_path, mode):
    data, config, targets, path, root, old_nav, _, old_commits = _snapshot_prefix(tmp_path)
    day = data.close.index[20]
    directory = root / day.strftime("%Y-%m-%d")
    if mode == "missing-file":
        (directory / "close.parquet").unlink()
    elif mode == "corrupt-parquet":
        with (directory / "close.parquet").open("ab") as handle:
            handle.write(b"tamper")
    else:
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["dataset_id"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="snapshot integrity verification failed"):
        replay_targets_persistently(
            data, targets, config, path, snapshot_root=root, reset=False
        )
    with PaperLedger(path, base_currency="USD") as ledger:
        assert ledger.nav_history().equals(old_nav)
        assert ledger.session_commits().equals(old_commits)


def test_snapshot_dataset_id_and_root_must_match_committed_ledger(tmp_path):
    data, config, targets, path, root, old_nav, _, _ = _snapshot_prefix(tmp_path)
    wrong_root = tmp_path / "wrong-snapshot-root"
    with pytest.raises(ValueError, match="snapshot root conflicts"):
        replay_targets_persistently(
            data, targets, config, path, snapshot_root=wrong_root, reset=False
        )
    with pytest.raises(ValueError, match="existing session snapshots require"):
        replay_targets_persistently(data, targets, config, path, reset=False)
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE snapshots SET dataset_id=? WHERE timestamp=?",
            ("a" * 64, data.close.index[20].isoformat()),
        )
    with pytest.raises(ValueError, match="snapshot linkage mismatch"):
        replay_targets_persistently(
            data, targets, config, path, snapshot_root=root, reset=False
        )
    with PaperLedger(path, base_currency="USD") as ledger:
        assert ledger.nav_history().equals(old_nav)


def test_snapshot_valid_manifest_with_revised_data_still_fails_digest(tmp_path):
    data, config, targets, path, root, old_nav, _, _ = _snapshot_prefix(tmp_path)
    stamp = data.close.index[20]
    directory = root / stamp.strftime("%Y-%m-%d")
    saved = load_market_data_snapshot(directory)
    edited_close = saved.close.copy()
    edited_close.at[stamp, "AAA"] += 1.0
    revised = replace(saved, close=edited_close)
    new_manifest = save_market_data_snapshot(revised, directory, overwrite=True)
    # Simulate a DB link rewrite: the already committed data fingerprint remains intact.
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE snapshots SET dataset_id=? WHERE timestamp=?",
            (new_manifest.dataset_id, stamp.isoformat()),
        )
        db.execute(
            "UPDATE session_commits SET snapshot_dataset_id=? WHERE timestamp=?",
            (new_manifest.dataset_id, stamp.isoformat()),
        )
    with pytest.raises(ValueError, match="snapshot market data mismatch"):
        replay_targets_persistently(
            data, targets, config, path, snapshot_root=root, reset=False
        )
    with PaperLedger(path, base_currency="USD") as ledger:
        assert ledger.nav_history().equals(old_nav)


@pytest.mark.parametrize("field", ["symbols", "start", "end"])
def test_snapshot_manifest_metadata_must_match_snapshot_contents(tmp_path, field):
    data, config, targets, path, root, _, _, _ = _snapshot_prefix(tmp_path)
    stamp = data.close.index[20]
    manifest_path = root / stamp.strftime("%Y-%m-%d") / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = ["WRONG"] if field == "symbols" else "1999-01-01"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="snapshot manifest metadata mismatch"):
        replay_targets_persistently(
            data, targets, config, path, snapshot_root=root, reset=False
        )


def test_orphan_snapshot_db_row_is_rejected(tmp_path):
    data, config, targets, path, root, _, _, _ = _snapshot_prefix(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO snapshots(timestamp, dataset_id, path) VALUES(?, ?, ?)",
            ("2030-01-01T00:00:00", "a" * 64, str(root / "unexpected")),
        )
    with pytest.raises(ValueError, match="snapshot linkage has an uncommitted session"):
        replay_targets_persistently(
            data, targets, config, path, snapshot_root=root, reset=False
        )
