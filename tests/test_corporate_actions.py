import pandas as pd
import pytest

from quant_fund_lab.backtest import run_backtest
from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.corporate_actions import apply_cash_dividend_events, apply_stock_split_events
from quant_fund_lab.data import MarketData
from quant_fund_lab.execution import PortfolioState


def test_split_and_dividend_adjust_actual_position_and_cash():
    state = PortfolioState(cash=100.0, shares={"AAA": 10})
    split_events = apply_stock_split_events(
        state,
        pd.Series({"AAA": 2.0}),
        pd.Series({"AAA": 50.0}),
        pd.Timestamp("2026-01-05"),
    )
    assert state.shares["AAA"] == 20
    assert state.cash == pytest.approx(100.0)
    assert split_events[0].quantity_before == 10
    assert split_events[0].quantity_after == 20

    dividend_events = apply_cash_dividend_events(
        state,
        pd.Series({"AAA": 1.25}),
        pd.Timestamp("2026-01-05"),
    )
    assert state.cash == pytest.approx(125.0)
    assert dividend_events[0].cash_value == pytest.approx(25.0)


def test_reverse_split_fractional_share_becomes_cash_in_lieu():
    state = PortfolioState(cash=0.0, shares={"AAA": 11})
    events = apply_stock_split_events(
        state,
        pd.Series({"AAA": 0.5}),
        pd.Series({"AAA": 20.0}),
        pd.Timestamp("2026-01-05"),
    )
    assert state.shares["AAA"] == 5
    assert state.cash == pytest.approx(10.0)
    assert events[0].cash_value_local == pytest.approx(10.0)


def _raw_split_market_data() -> MarketData:
    dates = pd.bdate_range("2025-01-02", periods=80)
    adjusted_aaa = pd.Series(50.0 + 0.2 * pd.RangeIndex(len(dates)), index=dates, dtype=float)
    adjusted_bbb = pd.Series(50.0, index=dates, dtype=float)
    adjusted_close = pd.DataFrame({"AAA": adjusted_aaa, "BBB": adjusted_bbb})
    adjusted_open = adjusted_close.copy()
    raw_close = adjusted_close.copy()
    raw_open = adjusted_open.copy()
    split_date = dates[50]
    raw_close.loc[: dates[49], "AAA"] *= 2.0
    raw_open.loc[: dates[49], "AAA"] *= 2.0
    splits = pd.DataFrame(0.0, index=dates, columns=["AAA", "BBB"])
    splits.loc[split_date, "AAA"] = 2.0
    dividends = pd.DataFrame(0.0, index=dates, columns=["AAA", "BBB"])
    dividends.loc[dates[60], "AAA"] = 1.0
    return MarketData(
        open=adjusted_open,
        close=adjusted_close,
        raw_open=raw_open,
        raw_close=raw_close,
        volume=pd.DataFrame(2_000_000.0, index=dates, columns=["AAA", "BBB"]),
        stock_splits=splits,
        dividends=dividends,
        membership=pd.DataFrame(True, index=dates, columns=["AAA", "BBB"]),
    )


def test_raw_execution_backtest_records_corporate_actions_when_position_is_held():
    data = _raw_split_market_data()
    config = BacktestConfig(
        initial_cash=100_000.0,
        execution_price_basis="raw",
        strategy=StrategyConfig(
            warmup_days=30,
            rebalance_every=5,
            max_weight=0.8,
            regime_enabled=False,
            factor_neutralization=False,
            risk_aversion=0.2,
        ),
    )
    result = run_backtest(data, config)
    assert not result.corporate_actions.empty
    assert "stock_split" in set(result.corporate_actions["action"])
    assert result.equity_curve["equity"].gt(0.0).all()


def test_adjusted_execution_mode_does_not_double_count_corporate_actions():
    data = _raw_split_market_data()
    config = BacktestConfig(
        initial_cash=100_000.0,
        execution_price_basis="adjusted",
        strategy=StrategyConfig(warmup_days=30, rebalance_every=5, max_weight=0.8),
    )
    result = run_backtest(data, config)
    assert result.corporate_actions.empty
