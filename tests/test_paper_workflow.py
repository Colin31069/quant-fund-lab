"""M11-6: explicit, non-destructive local paper ledger workflow."""

from dataclasses import replace

import pandas as pd
import pytest

from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.paper_live import PaperLedger, replay_targets_persistently
from quant_fund_lab.paper_workflow import plan_persistent_paper_run


def _case():
    data = synthetic_market_data(symbols=("AAA", "BBB"), periods=32, seed=71)
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


def test_missing_ledger_requires_explicit_create_choice(tmp_path):
    path = tmp_path / "paper.sqlite"
    with pytest.raises(FileNotFoundError, match="choose rebuild to create"):
        plan_persistent_paper_run(path, "continue")
    assert not path.exists()
    assert plan_persistent_paper_run(path, "rebuild")
    assert not path.exists()


def test_rebuild_requires_separate_confirmation_and_never_deletes_during_planning(
    tmp_path,
):
    path = tmp_path / "paper.sqlite"
    path.write_bytes(b"prior virtual ledger")
    with pytest.raises(ValueError, match="requires explicit confirmation"):
        plan_persistent_paper_run(path, "rebuild")
    assert path.read_bytes() == b"prior virtual ledger"
    assert plan_persistent_paper_run(path, "rebuild", confirmed_rebuild=True)
    assert path.read_bytes() == b"prior virtual ledger"
    assert plan_persistent_paper_run(path, "continue") is False
    assert path.read_bytes() == b"prior virtual ledger"


def test_invalid_mode_and_directory_are_not_treated_as_ledgers(tmp_path):
    path = tmp_path / "paper.sqlite"
    with pytest.raises(ValueError, match="mode must be"):
        plan_persistent_paper_run(path, "unsafe-reset", confirmed_rebuild=True)
    path.mkdir()
    with pytest.raises(ValueError, match="not a regular file"):
        plan_persistent_paper_run(path, "continue")
    with pytest.raises(ValueError, match="not a regular file"):
        plan_persistent_paper_run(path, "rebuild", confirmed_rebuild=True)


def test_safe_resume_from_ui_plan_preserves_fills_and_commits(tmp_path):
    data, config, targets = _case()
    path = tmp_path / "paper.sqlite"
    root = tmp_path / "paper-snapshots"
    initial_reset = plan_persistent_paper_run(path, "rebuild")
    first = replay_targets_persistently(
        data.slice(end=data.close.index[24]),
        targets,
        config,
        path,
        snapshot_root=root,
        reset=initial_reset,
    )
    try:
        prior_nav = first.nav_history()
        prior_fills = first.fills()
        prior_commits = first.session_commits()
    finally:
        first.close()

    resume_reset = plan_persistent_paper_run(path, "continue")
    assert resume_reset is False
    second = replay_targets_persistently(
        data, targets, config, path, snapshot_root=root, reset=resume_reset
    )
    clean = replay_targets_persistently(
        data, targets, config, tmp_path / "clean.sqlite",
        snapshot_root=tmp_path / "clean-snapshots"
    )
    try:
        assert second.nav_history().loc[prior_nav.index].equals(prior_nav)
        assert second.fills().iloc[: len(prior_fills)].equals(prior_fills)
        assert second.session_commits().loc[prior_commits.index].equals(prior_commits)
        assert second.nav_history().equals(clean.nav_history())
        assert second.orders().equals(clean.orders())
        assert second.session_commits().equals(clean.session_commits())
    finally:
        second.close()
        clean.close()


def test_ui_plan_safe_resume_fails_closed_without_erasing_ledger(tmp_path):
    data, config, targets = _case()
    path = tmp_path / "safe.sqlite"
    ledger = replay_targets_persistently(
        data.slice(end=data.close.index[24]), targets, config, path
    )
    try:
        prior_nav = ledger.nav_history()
        prior_commits = ledger.session_commits()
    finally:
        ledger.close()

    revised = data.close.copy()
    revised.at[data.close.index[22], "AAA"] += 1.0
    modified_data = replace(data, close=revised)
    with pytest.raises(ValueError, match="replay data fingerprint mismatch"):
        replay_targets_persistently(
            modified_data,
            targets,
            config,
            path,
            reset=plan_persistent_paper_run(path, "continue"),
        )
    with PaperLedger(path, base_currency="USD") as reopened:
        assert reopened.nav_history().equals(prior_nav)
        assert reopened.session_commits().equals(prior_commits)


def test_explicit_rebuild_is_the_only_ui_mode_that_resets_existing_history(tmp_path):
    data, config, targets = _case()
    path = tmp_path / "rebuild.sqlite"
    original = replay_targets_persistently(
        data.slice(end=data.close.index[24]), targets, config, path
    )
    original.close()

    with pytest.raises(ValueError, match="requires explicit confirmation"):
        plan_persistent_paper_run(path, "rebuild")
    with PaperLedger(path, base_currency="USD") as saved:
        assert len(saved.nav_history()) == 6
        assert saved.initial_cash == config.initial_cash

    changed = replace(config, initial_cash=200_000.0)
    reset = plan_persistent_paper_run(path, "rebuild", confirmed_rebuild=True)
    fresh = replay_targets_persistently(data, targets, changed, path, reset=reset)
    try:
        assert fresh.initial_cash == 200_000.0
        assert len(fresh.nav_history()) == len(data.close.index[19:])
        assert fresh.replay_execution_config()["initial_cash"] == 200_000.0
    finally:
        fresh.close()
