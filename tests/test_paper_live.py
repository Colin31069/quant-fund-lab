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


def test_paper_ledger_raw_corporate_actions_adjust_cost_basis_and_realized_pnl(tmp_path):
    config = BacktestConfig(
        initial_cash=10_000.0,
        base_currency="USD",
        execution_price_basis="raw",
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
    path = tmp_path / "raw.sqlite"
    with PaperLedger(path, 10_000.0, "USD", reset=True) as ledger:
        ledger.ensure_execution_price_basis("raw")
        ledger.submit_target_orders(
            pd.Timestamp("2026-01-02"),
            pd.Series({"AAA": 0.10}),
            pd.Series({"AAA": 100.0}),
            config,
        )
        ledger.process_open(
            pd.Timestamp("2026-01-05"),
            pd.Series({"AAA": 100.0}),
            pd.Series({"AAA": 100_000.0}),
            pd.Series({"AAA": 100.0}),
            config,
        )
        before = ledger.positions().loc["AAA"]
        assert int(before["quantity"]) == 10
        assert before["avg_cost_base"] == pytest.approx(100.0)
        ledger.process_corporate_actions(
            pd.Timestamp("2026-01-06"),
            pd.Series({"AAA": 2.0}),
            pd.Series({"AAA": 1.0}),
            pd.Series({"AAA": 50.0}),
        )
        after = ledger.positions().loc["AAA"]
        assert int(after["quantity"]) == 20
        assert after["avg_cost_base"] == pytest.approx(50.0)
        assert after["realized_pnl_base"] == pytest.approx(20.0)
        assert ledger.cash == pytest.approx(9_020.0)
        actions = ledger.corporate_actions()
        assert list(actions["action"]) == ["stock_split", "cash_dividend"]


def test_paper_ledger_dividend_withholding_is_net_cash_and_auditable(tmp_path):
    config = BacktestConfig(
        initial_cash=10_000.0,
        base_currency="USD",
        execution_price_basis="raw",
        dividend_withholding=DividendWithholdingConfig(us_rate=0.30),
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
    path = tmp_path / "withholding.sqlite"
    with PaperLedger(path, 10_000.0, "USD", reset=True) as ledger:
        ledger.ensure_execution_price_basis("raw")
        ledger.submit_target_orders(
            pd.Timestamp("2026-01-02"),
            pd.Series({"AAA": 0.10}),
            pd.Series({"AAA": 100.0}),
            config,
        )
        ledger.process_open(
            pd.Timestamp("2026-01-05"),
            pd.Series({"AAA": 100.0}),
            pd.Series({"AAA": 100_000.0}),
            pd.Series({"AAA": 100.0}),
            config,
        )
        ledger.process_corporate_actions(
            pd.Timestamp("2026-01-06"),
            pd.Series({"AAA": 0.0}),
            pd.Series({"AAA": 2.0}),
            pd.Series({"AAA": 100.0}),
            market_codes=pd.Series({"AAA": "US"}),
            dividend_withholding=config.dividend_withholding,
        )
        assert ledger.cash == pytest.approx(9_014.0)
        assert ledger.positions().loc["AAA", "realized_pnl_base"] == pytest.approx(14.0)
        event = ledger.corporate_actions().iloc[-1]
        assert event["gross_cash_value"] == pytest.approx(20.0)
        assert event["withholding_tax"] == pytest.approx(6.0)
        assert event["withholding_rate"] == pytest.approx(0.30)
        assert event["cash_value"] == pytest.approx(14.0)


    with PaperLedger(path, base_currency="USD") as reopened:
        reopened.ensure_dividend_withholding(DividendWithholdingConfig(us_rate=0.30))
        with pytest.raises(ValueError, match="withholding assumptions"):
            reopened.ensure_dividend_withholding(DividendWithholdingConfig(us_rate=0.0))


def test_existing_paper_ledger_migrates_corporate_action_audit_columns(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE corporate_actions (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            quantity_before INTEGER NOT NULL,
            quantity_after INTEGER NOT NULL,
            ratio_or_amount REAL NOT NULL,
            cash_value REAL NOT NULL,
            cash_value_local REAL NOT NULL,
            fx_to_base REAL NOT NULL,
            realized_pnl_delta REAL NOT NULL
        );
        INSERT INTO metadata(key, value) VALUES
            ('initial_cash', '10000.0'),
            ('cash', '10020.0'),
            ('base_currency', '"USD"');
        INSERT INTO corporate_actions(
            timestamp, symbol, action, quantity_before, quantity_after,
            ratio_or_amount, cash_value, cash_value_local, fx_to_base, realized_pnl_delta
        ) VALUES('2026-01-06', 'AAA', 'cash_dividend', 10, 10, 2.0, 20.0, 20.0, 1.0, 20.0);
        """
    )
    connection.commit()
    connection.close()

    with PaperLedger(path, base_currency="USD") as ledger:
        event = ledger.corporate_actions().iloc[0]
        assert event["gross_cash_value"] == pytest.approx(20.0)
        assert event["gross_cash_value_local"] == pytest.approx(20.0)
        assert event["withholding_tax"] == pytest.approx(0.0)
        assert event["withholding_tax_local"] == pytest.approx(0.0)
        assert event["withholding_rate"] == pytest.approx(0.0)
        ledger.ensure_dividend_withholding(DividendWithholdingConfig())
        with pytest.raises(ValueError, match="withholding assumptions"):
            ledger.ensure_dividend_withholding(DividendWithholdingConfig(us_rate=0.30))


def test_m9_1_ledger_infers_existing_us_withholding_before_locking_metadata(tmp_path):
    import sqlite3

    path = tmp_path / "m9-1.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE corporate_actions (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            quantity_before INTEGER NOT NULL,
            quantity_after INTEGER NOT NULL,
            ratio_or_amount REAL NOT NULL,
            cash_value REAL NOT NULL,
            cash_value_local REAL NOT NULL,
            local_currency TEXT NOT NULL DEFAULT '',
            fx_to_base REAL NOT NULL,
            gross_cash_value REAL NOT NULL DEFAULT 0,
            gross_cash_value_local REAL NOT NULL DEFAULT 0,
            withholding_tax REAL NOT NULL DEFAULT 0,
            withholding_tax_local REAL NOT NULL DEFAULT 0,
            realized_pnl_delta REAL NOT NULL
        );
        INSERT INTO metadata(key, value) VALUES
            ('initial_cash', '10000.0'),
            ('cash', '10014.0'),
            ('base_currency', '"USD"');
        INSERT INTO corporate_actions(
            timestamp, symbol, action, quantity_before, quantity_after,
            ratio_or_amount, cash_value, cash_value_local, local_currency, fx_to_base,
            gross_cash_value, gross_cash_value_local, withholding_tax, withholding_tax_local,
            realized_pnl_delta
        ) VALUES(
            '2026-01-06', 'AAA', 'cash_dividend', 10, 10,
            2.0, 14.0, 14.0, 'USD', 1.0, 20.0, 20.0, 6.0, 6.0, 14.0
        );
        """
    )
    connection.commit()
    connection.close()

    with PaperLedger(path, base_currency="USD") as ledger:
        event = ledger.corporate_actions().iloc[0]
        assert event["withholding_rate"] == pytest.approx(0.30)
        ledger.ensure_dividend_withholding(DividendWithholdingConfig(us_rate=0.30))
        with pytest.raises(ValueError, match="withholding assumptions"):
            ledger.ensure_dividend_withholding(DividendWithholdingConfig(us_rate=0.0))


def test_paper_ledger_uses_explicit_cash_in_lieu_settlement_price(tmp_path):
    config = BacktestConfig(
        initial_cash=10_000.0,
        base_currency="USD",
        execution_price_basis="raw",
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
    path = tmp_path / "cash-in-lieu.sqlite"
    with PaperLedger(path, 10_000.0, "USD", reset=True) as ledger:
        ledger.ensure_execution_price_basis("raw")
        ledger.submit_target_orders(
            pd.Timestamp("2026-01-02"),
            pd.Series({"AAA": 0.11}),
            pd.Series({"AAA": 100.0}),
            config,
        )
        ledger.process_open(
            pd.Timestamp("2026-01-05"),
            pd.Series({"AAA": 100.0}),
            pd.Series({"AAA": 100_000.0}),
            pd.Series({"AAA": 100.0}),
            config,
        )
        assert int(ledger.positions().loc["AAA", "quantity"]) == 11

        ledger.process_corporate_actions(
            pd.Timestamp("2026-01-06"),
            pd.Series({"AAA": 0.5}),
            pd.Series({"AAA": 0.0}),
            pd.Series({"AAA": 20.0}),
            cash_in_lieu_prices=pd.Series({"AAA": 18.0}),
        )
        event = ledger.corporate_actions().iloc[-1]
        assert int(ledger.positions().loc["AAA", "quantity"]) == 5
        assert event["cash_in_lieu_price"] == pytest.approx(18.0)
        assert event["cash_in_lieu_price_source"] == "provider_settlement"
        assert event["cash_value"] == pytest.approx(9.0)
        assert event["realized_pnl_delta"] == pytest.approx(-91.0)


def test_split_rebases_persistent_open_order_quantity(tmp_path):
    config = _low_participation_config()
    path = tmp_path / "orders.sqlite"
    with PaperLedger(path, 100_000.0, "USD", reset=True) as ledger:
        ledger.ensure_execution_price_basis("raw")
        ledger.submit_target_orders(
            pd.Timestamp("2026-01-02"),
            pd.Series({"AAA": 0.5}),
            pd.Series({"AAA": 100.0}),
            config,
        )
        before = ledger.orders().iloc[0]
        ledger.process_corporate_actions(
            pd.Timestamp("2026-01-05"),
            pd.Series({"AAA": 2.0}),
            pd.Series({"AAA": 0.0}),
            pd.Series({"AAA": 50.0}),
        )
        after = ledger.orders().iloc[0]
        assert int(after["remaining_qty"]) == int(before["remaining_qty"]) * 2


def test_paper_target_sizing_uses_market_metadata_for_internal_tw_asset(tmp_path):
    symbol = "ASSET@@tw-security"
    config = BacktestConfig(
        initial_cash=1_000_000.0,
        base_currency="USD",
        strategy=StrategyConfig(warmup_days=20),
        us_costs=MarketCostConfig(
            commission_bps=0.0,
            slippage_bps=0.0,
            impact_coefficient=0.0,
            max_participation=1.0,
            lot_size=1,
        ),
        tw_costs=MarketCostConfig(
            commission_bps=0.0,
            sell_tax_bps=0.0,
            slippage_bps=0.0,
            impact_coefficient=0.0,
            max_participation=1.0,
            lot_size=1_000,
            price_limit_pct=0.10,
        ),
    )
    with PaperLedger(tmp_path / "metadata-orders.sqlite", 1_000_000.0, "USD", reset=True) as ledger:
        ledger.submit_target_orders(
            pd.Timestamp("2026-01-02"),
            pd.Series({symbol: 0.53}),
            pd.Series({symbol: 3_200.0}),
            config,
            fx_to_base=pd.Series({symbol: 1.0 / 32.0}),
            market_codes=pd.Series({symbol: "TW"}),
        )
        order = ledger.orders().iloc[0]
        assert int(order["requested_qty"]) == 5_000
        assert int(order["requested_qty"]) % 1_000 == 0


def test_persistent_replay_uses_transition_day_metadata_and_masks_old_reference(tmp_path):
    dates = pd.bdate_range("2026-01-02", periods=5)
    symbol = "ASSET@@global-security"
    prices = pd.DataFrame(
        {symbol: [100.0, 100.0, 100.0, 3_200.0, 3_200.0]},
        index=dates,
    )
    data = MarketData(
        open=prices.copy(),
        close=prices.copy(),
        volume=pd.DataFrame(1_000_000.0, index=dates, columns=[symbol]),
        market_codes=pd.DataFrame(
            ["US", "US", "US", "TW", "TW"],
            index=dates,
            columns=[symbol],
        ),
        currency_codes=pd.DataFrame(
            ["USD", "USD", "USD", "TWD", "TWD"],
            index=dates,
            columns=[symbol],
        ),
    )
    converted = attach_fx_rates(
        data,
        "USD",
        usd_twd=pd.Series(32.0, index=dates, dtype=float),
    )
    config = BacktestConfig(
        initial_cash=1_000_000.0,
        base_currency="USD",
        strategy=StrategyConfig(warmup_days=20),
        us_costs=MarketCostConfig(
            commission_bps=0.0,
            slippage_bps=0.0,
            impact_coefficient=0.0,
            max_participation=1.0,
            lot_size=1,
        ),
        tw_costs=MarketCostConfig(
            commission_bps=0.0,
            sell_tax_bps=0.0,
            slippage_bps=0.0,
            impact_coefficient=0.0,
            max_participation=1.0,
            lot_size=1_000,
            price_limit_pct=0.10,
        ),
    )
    targets = pd.DataFrame([{symbol: 0.5}], index=[dates[2]])
    ledger = replay_targets_persistently(
        converted,
        targets,
        config,
        tmp_path / "transition.sqlite",
        reset=True,
    )
    try:
        fills = ledger.fills()
        assert len(fills) == 1
        fill = fills.iloc[0]
        assert pd.Timestamp(fill["timestamp"]) == dates[3]
        assert fill["local_currency"] == "TWD"
        assert int(fill["quantity"]) == 5_000
        assert int(fill["quantity"]) % 1_000 == 0
        assert ledger.orders().iloc[0]["status"] == "FILLED"
        assert ledger.nav_history()["reconciliation_error"].abs().max() < 1e-8
    finally:
        ledger.close()


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


def test_raw_persistent_replay_records_corporate_action_events(tmp_path):
    data = synthetic_market_data(symbols=("AAA", "BBB"), periods=90, seed=24)
    dates = data.close.index
    raw_open = data.open.copy()
    raw_close = data.close.copy()
    split_date = dates[55]
    raw_open.loc[: dates[54], "AAA"] *= 2.0
    raw_close.loc[: dates[54], "AAA"] *= 2.0
    splits = data.stock_splits.copy()
    splits.loc[split_date, "AAA"] = 2.0
    dividends = data.dividends.copy()
    dividends.loc[dates[65], "AAA"] = 0.5
    raw_data = MarketData(
        open=data.open,
        close=data.close,
        raw_open=raw_open,
        raw_close=raw_close,
        volume=data.volume,
        membership=data.membership,
        stock_splits=splits,
        dividends=dividends,
    )
    config = BacktestConfig(
        initial_cash=250_000.0,
        execution_price_basis="raw",
        strategy=StrategyConfig(warmup_days=20, rebalance_every=5, max_weight=0.6),
    )
    signals = dates[30:75:10]
    targets = pd.DataFrame([{"AAA": 0.5, "BBB": 0.4} for _ in signals], index=signals)
    ledger = replay_targets_persistently(
        raw_data,
        targets,
        config,
        tmp_path / "raw-replay.sqlite",
        reset=True,
    )
    try:
        actions = ledger.corporate_actions()
        assert not actions.empty
        assert "stock_split" in set(actions["action"])
        assert ledger.nav_history()["reconciliation_error"].abs().max() < 1e-8
    finally:
        ledger.close()
