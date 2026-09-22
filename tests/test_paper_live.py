import pandas as pd
import pytest

from quant_fund_lab.config import BacktestConfig, MarketCostConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.paper_live import PaperLedger, replay_targets_persistently


def _low_participation_config() -> BacktestConfig:
    return BacktestConfig(
        initial_cash=100_000.0,
        base_currency="USD",
        strategy=StrategyConfig(warmup_days=20),
        us_costs=MarketCostConfig(
            commission_bps=0.0,
            sec_fee_per_million=0.0,
            slippage_bps=0.0,
            impact_coefficient=0.0,
            max_participation=0.10,
            lot_size=1,
        ),
    )


def test_paper_ledger_persists_partial_order_and_retries(tmp_path):
    config = _low_participation_config()
    path = tmp_path / "paper.sqlite"
    signal = pd.Timestamp("2026-01-02")
    with PaperLedger(path, 100_000.0, "USD", reset=True) as ledger:
        ids = ledger.submit_target_orders(
            signal,
            pd.Series({"AAPL": 1.0}),
            pd.Series({"AAPL": 100.0}),
            config,
        )
        assert len(ids) == 1
        fills = ledger.process_open(
            pd.Timestamp("2026-01-05"),
            pd.Series({"AAPL": 100.0}),
            pd.Series({"AAPL": 1_000.0}),
            pd.Series({"AAPL": 99.0}),
            config,
        )
        assert fills[0].quantity == 100
        order = ledger.orders().iloc[0]
        assert order["status"] == "PARTIAL"
        assert int(order["remaining_qty"]) > 0

    with PaperLedger(path, base_currency="USD") as reopened:
        assert reopened.orders().iloc[0]["status"] == "PARTIAL"
        second = reopened.process_open(
            pd.Timestamp("2026-01-06"),
            pd.Series({"AAPL": 100.0}),
            pd.Series({"AAPL": 20_000.0}),
            pd.Series({"AAPL": 100.0}),
            config,
        )
        assert second
        assert reopened.orders().iloc[0]["status"] == "FILLED"
        assert reopened.portfolio_state().shares["AAPL"] > 0


def test_mark_close_persists_pnl_benchmark_and_reconciles(tmp_path):
    config = _low_participation_config()
    path = tmp_path / "paper.sqlite"
    with PaperLedger(path, 100_000.0, "USD", reset=True) as ledger:
        ledger.submit_target_orders(
            pd.Timestamp("2026-01-02"),
            pd.Series({"AAPL": 0.5}),
            pd.Series({"AAPL": 100.0}),
            config,
        )
        ledger.process_open(
            pd.Timestamp("2026-01-05"),
            pd.Series({"AAPL": 100.0}),
            pd.Series({"AAPL": 50_000.0}),
            pd.Series({"AAPL": 99.0}),
            config,
        )
        marked = ledger.mark_close(
            pd.Timestamp("2026-01-05"),
            pd.Series({"AAPL": 105.0}),
            benchmark_close_base=500.0,
        )
        assert marked["unrealized_pnl"] > 0.0
        assert abs(marked["reconciliation_error"]) < 1e-8
        history = ledger.nav_history()
        assert history.iloc[-1]["benchmark_equity"] == pytest.approx(100_000.0)


def test_persistent_replay_records_daily_snapshots_and_nav(tmp_path):
    data = synthetic_market_data(symbols=("AAA", "BBB"), periods=90, seed=14)
    config = BacktestConfig(
        initial_cash=250_000.0,
        strategy=StrategyConfig(warmup_days=20, rebalance_every=5, max_weight=0.6),
    )
    signals = data.close.index[25:70:10]
    targets = pd.DataFrame(
        [{"AAA": 0.5, "BBB": 0.4} for _ in signals],
        index=signals,
    )
    ledger = replay_targets_persistently(
        data,
        targets,
        config,
        tmp_path / "replay.sqlite",
        snapshot_root=tmp_path / "snapshots",
        reset=True,
    )
    try:
        nav = ledger.nav_history()
        snapshots = ledger.snapshots()
        assert not nav.empty
        assert len(snapshots) == len(nav)
        assert nav["equity"].gt(0.0).all()
        assert nav["reconciliation_error"].abs().max() < 1e-8
        assert not ledger.fills().empty
    finally:
        ledger.close()
