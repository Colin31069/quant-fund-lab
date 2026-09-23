import pandas as pd
import pytest

from quant_fund_lab.backtest import run_backtest
from quant_fund_lab.config import BacktestConfig, DividendWithholdingConfig, StrategyConfig
from quant_fund_lab.corporate_actions import apply_cash_dividend_events, apply_stock_split_events
from quant_fund_lab.data import MarketData
from quant_fund_lab.execution import PortfolioState
from quant_fund_lab.tax_analytics import dividend_tax_by_currency, summarize_dividend_tax


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


def test_dividend_withholding_records_gross_tax_and_net_cash():
    state = PortfolioState(cash=100.0, shares={"ASSET@@us-security": 10})
    events = apply_cash_dividend_events(
        state,
        pd.Series({"ASSET@@us-security": 2.0}),
        pd.Timestamp("2026-01-05"),
        market_codes=pd.Series({"ASSET@@us-security": "US"}),
        withholding=DividendWithholdingConfig(us_rate=0.30),
    )

    event = events[0]
    assert state.cash == pytest.approx(114.0)
    assert event.gross_cash_value_local == pytest.approx(20.0)
    assert event.withholding_tax_local == pytest.approx(6.0)
    assert event.cash_value_local == pytest.approx(14.0)
    assert event.gross_cash_value == pytest.approx(20.0)
    assert event.withholding_tax == pytest.approx(6.0)
    assert event.withholding_rate == pytest.approx(0.30)
    assert event.cash_value == pytest.approx(14.0)


def test_dividend_withholding_config_rejects_invalid_rates():
    with pytest.raises(ValueError, match="us_rate"):
        DividendWithholdingConfig(us_rate=1.01)
    with pytest.raises(ValueError, match="tw_rate"):
        DividendWithholdingConfig(tw_rate=-0.01)


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


def test_raw_backtest_applies_configured_dividend_withholding():
    data = _raw_split_market_data()
    config = BacktestConfig(
        initial_cash=100_000.0,
        execution_price_basis="raw",
        dividend_withholding=DividendWithholdingConfig(us_rate=0.30),
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
    dividends = result.corporate_actions[
        result.corporate_actions["action"].eq("cash_dividend")
    ]
    assert not dividends.empty
    event = dividends.iloc[0]
    assert event["withholding_tax"] == pytest.approx(event["gross_cash_value"] * 0.30)
    assert event["withholding_rate"] == pytest.approx(0.30)
    assert event["cash_value"] == pytest.approx(event["gross_cash_value"] * 0.70)

    summary = summarize_dividend_tax(result.corporate_actions)
    assert summary["dividend_event_count"] == 1
    assert summary["effective_withholding_rate"] == pytest.approx(0.30)
    assert summary["gross_dividend_cash"] == pytest.approx(event["gross_cash_value"])
    assert summary["withholding_tax"] == pytest.approx(event["withholding_tax"])
    assert summary["net_dividend_cash"] == pytest.approx(event["cash_value"])
    by_currency = dividend_tax_by_currency(result.corporate_actions)
    assert list(by_currency.index) == ["USD"]
    assert by_currency.loc["USD", "effective_withholding_rate"] == pytest.approx(0.30)


def test_dividend_tax_analytics_rejects_unreconciled_cashflow():
    actions = pd.DataFrame(
        [
            {
                "action": "cash_dividend",
                "cash_value": 8.0,
                "gross_cash_value": 10.0,
                "withholding_tax": 3.0,
                "local_currency": "USD",
            }
        ]
    )
    with pytest.raises(ValueError, match="does not reconcile"):
        summarize_dividend_tax(actions)



def test_adjusted_execution_mode_does_not_double_count_corporate_actions():
    data = _raw_split_market_data()
    config = BacktestConfig(
        initial_cash=100_000.0,
        execution_price_basis="adjusted",
        strategy=StrategyConfig(warmup_days=30, rebalance_every=5, max_weight=0.8),
    )
    result = run_backtest(data, config)
    assert result.corporate_actions.empty
