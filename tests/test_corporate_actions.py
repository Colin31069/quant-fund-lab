import pandas as pd
import pytest

from quant_fund_lab.backtest import run_backtest
from quant_fund_lab.config import BacktestConfig, DividendWithholdingConfig, StrategyConfig
from quant_fund_lab.corporate_actions import (
    apply_cash_dividend_events,
    apply_stock_split_events,
    mark_cash_in_lieu_receivables,
    settle_cash_in_lieu_receivables,
)
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
    assert events[0].cash_in_lieu_price == pytest.approx(20.0)
    assert events[0].cash_in_lieu_price_source == "raw_open_fallback"


def test_reverse_split_prefers_explicit_cash_in_lieu_settlement_price():
    state = PortfolioState(cash=0.0, shares={"AAA": 11})
    events = apply_stock_split_events(
        state,
        pd.Series({"AAA": 0.5}),
        pd.Series({"AAA": 20.0}),
        pd.Timestamp("2026-01-05"),
        cash_in_lieu_prices=pd.Series({"AAA": 18.0}),
    )

    assert state.shares["AAA"] == 5
    assert state.cash == pytest.approx(9.0)
    event = events[0]
    assert event.cash_in_lieu_price == pytest.approx(18.0)
    assert event.cash_in_lieu_price_source == "provider_settlement"
    assert event.cash_value_local == pytest.approx(9.0)


def test_delayed_cash_in_lieu_is_receivable_until_settlement_date():
    state = PortfolioState(cash=100.0, shares={"AAA": 11})
    receivables = []
    split_date = pd.Timestamp("2026-01-05")
    settlement_date = pd.Timestamp("2026-01-07")

    events = apply_stock_split_events(
        state,
        pd.Series({"AAA": 0.5}),
        pd.Series({"AAA": 20.0}),
        split_date,
        cash_in_lieu_settlement_dates=pd.Series({"AAA": settlement_date}),
        receivables=receivables,
    )

    assert state.shares["AAA"] == 5
    assert state.cash == pytest.approx(100.0)
    assert len(receivables) == 1
    assert receivables[0].fractional_quantity == pytest.approx(0.5)
    assert events[0].cash_value == pytest.approx(0.0)
    assert events[0].cash_in_lieu_price_source == "pending_settlement"
    assert pd.Timestamp(events[0].cash_in_lieu_settlement_date) == settlement_date

    marked = mark_cash_in_lieu_receivables(
        receivables,
        pd.Series({"AAA": 21.0}),
    )
    assert marked == pytest.approx(10.5)
    state.receivable_value = marked
    assert state.equity(pd.Series({"AAA": 21.0})) == pytest.approx(215.5)

    settlement_events = settle_cash_in_lieu_receivables(
        state,
        receivables,
        settlement_date,
        pd.Series({"AAA": 18.0}),
    )
    state.receivable_value = mark_cash_in_lieu_receivables(
        receivables,
        pd.Series({"AAA": 18.0}),
    )
    assert receivables == []
    assert state.cash == pytest.approx(109.0)
    assert state.receivable_value == pytest.approx(0.0)
    assert settlement_events[0].action == "cash_in_lieu_settlement"
    assert settlement_events[0].cash_value == pytest.approx(9.0)
    assert settlement_events[0].cash_in_lieu_price == pytest.approx(18.0)


def test_future_settlement_rejects_ex_date_price_to_avoid_lookahead():
    state = PortfolioState(cash=0.0, shares={"AAA": 11})
    with pytest.raises(ValueError, match="future cash-in-lieu settlement"):
        apply_stock_split_events(
            state,
            pd.Series({"AAA": 0.5}),
            pd.Series({"AAA": 20.0}),
            pd.Timestamp("2026-01-05"),
            cash_in_lieu_prices=pd.Series({"AAA": 18.0}),
            cash_in_lieu_settlement_dates=pd.Series(
                {"AAA": pd.Timestamp("2026-01-07")}
            ),
            receivables=[],
        )


def _raw_split_market_data(
    split_ratio: float = 2.0,
    cash_in_lieu_price=None,
    settlement_delay: int = 0,
) -> MarketData:
    dates = pd.bdate_range("2025-01-02", periods=80)
    adjusted_aaa = pd.Series(50.0 + 0.2 * pd.RangeIndex(len(dates)), index=dates, dtype=float)
    adjusted_bbb = pd.Series(50.0, index=dates, dtype=float)
    adjusted_close = pd.DataFrame({"AAA": adjusted_aaa, "BBB": adjusted_bbb})
    adjusted_open = adjusted_close.copy()
    raw_close = adjusted_close.copy()
    raw_open = adjusted_open.copy()
    split_date = dates[50]
    raw_close.loc[: dates[49], "AAA"] *= split_ratio
    raw_open.loc[: dates[49], "AAA"] *= split_ratio
    splits = pd.DataFrame(0.0, index=dates, columns=["AAA", "BBB"])
    splits.loc[split_date, "AAA"] = split_ratio
    settlements = None
    settlement_dates = None
    if cash_in_lieu_price is not None:
        settlements = pd.DataFrame(float("nan"), index=dates, columns=["AAA", "BBB"])
        if settlement_delay > 0:
            settlement_date = dates[50 + settlement_delay]
            settlements.loc[settlement_date, "AAA"] = cash_in_lieu_price
            settlement_dates = pd.DataFrame(pd.NaT, index=dates, columns=["AAA", "BBB"])
            settlement_dates.loc[split_date, "AAA"] = settlement_date
        else:
            settlements.loc[split_date, "AAA"] = cash_in_lieu_price
    dividends = pd.DataFrame(0.0, index=dates, columns=["AAA", "BBB"])
    dividends.loc[dates[60], "AAA"] = 1.0
    return MarketData(
        open=adjusted_open,
        close=adjusted_close,
        raw_open=raw_open,
        raw_close=raw_close,
        volume=pd.DataFrame(2_000_000.0, index=dates, columns=["AAA", "BBB"]),
        stock_splits=splits,
        cash_in_lieu_prices=settlements,
        cash_in_lieu_settlement_dates=settlement_dates,
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


def test_raw_backtest_uses_explicit_cash_in_lieu_settlement_price():
    data = _raw_split_market_data(split_ratio=0.4, cash_in_lieu_price=61.25)
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
    split = result.corporate_actions[result.corporate_actions["action"].eq("stock_split")].iloc[0]
    assert split["cash_in_lieu_price"] == pytest.approx(61.25)
    assert split["cash_in_lieu_price_source"] == "provider_settlement"
    assert split["cash_value_local"] > 0.0


def test_raw_backtest_marks_delayed_cash_in_lieu_receivable_until_settlement():
    data = _raw_split_market_data(
        split_ratio=0.4,
        cash_in_lieu_price=61.25,
        settlement_delay=2,
    )
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
    actions = result.corporate_actions
    split = actions[actions["action"].eq("stock_split")].iloc[0]
    settlement = actions[actions["action"].eq("cash_in_lieu_settlement")].iloc[0]
    split_date = pd.Timestamp(split["timestamp"])
    settlement_date = pd.Timestamp(settlement["timestamp"])

    assert split["cash_value"] == pytest.approx(0.0)
    assert split["cash_in_lieu_price_source"] == "pending_settlement"
    assert settlement["cash_in_lieu_price"] == pytest.approx(61.25)
    assert settlement_date > split_date
    assert result.equity_curve.loc[split_date, "receivable_value"] > 0.0
    assert result.equity_curve.loc[settlement_date, "receivable_value"] == pytest.approx(0.0)


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
