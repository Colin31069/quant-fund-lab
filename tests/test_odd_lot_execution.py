from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quant_fund_lab import odd_lot_research
from quant_fund_lab.config import BacktestConfig, MarketCostConfig, StrategyConfig
from quant_fund_lab.data import MarketData
from quant_fund_lab.execution import PortfolioState
from quant_fund_lab.odd_lot_execution import round_price, simulate_limit_order, trade_fees
from quant_fund_lab.odd_lot_research import OddLotResearchConfig, run_odd_lot_research

STOCK = {"kind": "stock", "sell_tax_bps": 30.0, "price_limit_pct": 0.10}


def test_stock_and_etf_ticks_cross_price_bands_correctly():
    assert round_price(49.99, "stock", "up") == 50.0
    assert round_price(50.01, "stock", "up") == 50.1
    assert round_price(50.01, "etf", "up") == 50.05
    assert round_price(100.01, "stock", "down") == 100.0
    assert round_price(9.99, "stock", "down") == 9.99


def test_limit_order_expires_on_gap_and_partial_fill_respects_limit_and_fees():
    costs = MarketCostConfig(commission_bps=14.25, min_commission=20, sell_tax_bps=30,
                             max_participation=1, slippage_bps=0, impact_coefficient=0,
                             max_order_shares=999)
    state = PortfolioState(cash=10_000)
    args = (state, "2330.TW", "BUY", 10)
    fill, limit, reason = simulate_limit_order(*args, 102, 10_000, 100, pd.Timestamp("2024-01-02"),
                                                costs, STOCK, 0.01, 0.5, "fractional")
    assert fill is None and limit == 101 and reason == "limit_not_met"
    assert state.cash == 10_000 and state.shares == {}
    fill, limit, reason = simulate_limit_order(*args, 100.01, 10_000, 100, pd.Timestamp("2024-01-02"),
                                                costs, STOCK, 0.01, 0.5, "fractional")
    assert reason == "partial" and fill.quantity == 5
    assert fill.fill_price == 100.5 and fill.fill_price <= limit
    assert fill.fees == 20 and state.cash == pytest.approx(9477.5)


def test_fee_rounding_and_low_value_sale_with_net_payable():
    costs = MarketCostConfig(commission_bps=14.25, min_commission=20, sell_tax_bps=30,
                             max_participation=1, slippage_bps=0, impact_coefficient=0)
    assert trade_fees("SELL", 1010, costs, "floor") == 23
    assert trade_fees("SELL", 1010, costs, "nearest") == 23
    assert trade_fees("SELL", 1190, costs, "floor") == 23
    assert trade_fees("SELL", 1190, costs, "nearest") == 24
    state = PortfolioState(cash=100, shares={"2330.TW": 1})
    fill, _, _ = simulate_limit_order(state, "2330.TW", "SELL", 1, 5, 100, 5,
                                      pd.Timestamp("2024-01-02"), costs, STOCK, .01, .5, "fractional")
    assert fill is not None and fill.quantity == 1 and fill.fees > fill.gross_value
    assert state.cash == pytest.approx(100 + fill.gross_value - fill.fees)


def _research_fixture():
    dates = pd.bdate_range("2024-01-02", periods=65)
    prices = np.r_[np.linspace(90, 110, 40), [95, 94, 93], np.linspace(93, 100, 22)]
    close = pd.DataFrame({"2330.TW": prices, "2317.TW": prices * 0.8}, index=dates)
    data = MarketData(open=close, close=close, volume=close * 10_000)
    research = OddLotResearchConfig(strategy="momentum", momentum_lookback=5)
    base = BacktestConfig(initial_cash=100_000, base_currency="TWD",
                          strategy=StrategyConfig(warmup_days=30))
    return data, research, base


def test_settlement_reserves_buys_and_releases_sales_after_t_plus_two_open():
    data, research, base = _research_fixture()
    result = run_odd_lot_research(data, research, base)
    assert result.orders.status.eq("partial_expired").any()
    buy = result.settlements[result.settlements.side.eq("BUY")].iloc[0]
    sale = result.settlements[result.settlements.side.eq("SELL")].iloc[0]
    dates = data.close.index
    assert buy.settled_at == dates[dates.get_loc(buy.trade_date) + 2]
    assert sale.trade_date.weekday() == 4  # Friday
    assert sale.settled_at == pd.Timestamp("2024-03-05")  # Tuesday
    curve = result.equity_curve
    assert curve.loc[buy.trade_date, "buy_payables"] > 0
    assert curve.loc[buy.trade_date, "settled_cash"] - curve.loc[buy.trade_date, "cash"] == pytest.approx(
        curve.loc[buy.trade_date, "buy_payables"] + curve.loc[buy.trade_date, "sale_payables"])
    friday, monday, tuesday = map(pd.Timestamp, ("2024-03-01", "2024-03-04", "2024-03-05"))
    assert curve.loc[monday, "cash"] == pytest.approx(curve.loc[friday, "cash"])
    friday_proceeds = result.settlements.query("side == 'SELL' and trade_date == @friday").amount.sum()
    assert curve.loc[tuesday, "cash"] == pytest.approx(curve.loc[monday, "cash"] + friday_proceeds)
    positions = {symbol: 0 for symbol in data.symbols}
    for date, row in curve.iterrows():
        for fill in result.fills[result.fills.timestamp.eq(date)].itertuples():
            positions[fill.symbol] += fill.quantity if fill.side == "BUY" else -fill.quantity
        holdings = sum(positions[s] * data.raw_close.at[date, s] for s in data.symbols)
        assert row.equity == pytest.approx(row.cash + row.sale_receivables + holdings)
    assert all(result.orders.requested_quantity <= 999)


def test_missing_instrument_rules_fail_closed():
    data, research, base = _research_fixture()
    with pytest.raises(ValueError, match="missing explicit odd-lot instrument rules"):
        run_odd_lot_research(data, replace(research, instrument_rules={}), base)


def test_sale_cannot_fund_an_opening_order_until_after_t_plus_two(monkeypatch):
    dates = pd.bdate_range("2024-01-02", periods=37)
    close = pd.DataFrame(100.0, index=dates, columns=["2330.TW", "2317.TW"])
    data = MarketData(open=close, close=close, volume=close * 10_000)

    def targets(history, eligible, research, strategy, previous):
        selected = "2330.TW" if len(history) == 30 else "2317.TW"
        weights = pd.Series(0.0, index=history.columns)
        weights[selected] = 1.0
        return weights.copy(), weights

    monkeypatch.setattr(odd_lot_research, "_targets", targets)
    config = OddLotResearchConfig(strategy="momentum", risk_budget=100_000, max_positions=1,
                                  max_weight=1, rebalance_every=1, fill_fraction=1,
                                  commission_bps=0, min_commission=0, slippage_bps=0,
                                  impact_coefficient=0, max_participation=1,
                                  instrument_rules={symbol: {**STOCK, "sell_tax_bps": 0}
                                                    for symbol in close.columns})
    base = BacktestConfig(initial_cash=99_900, base_currency="TWD",
                          strategy=StrategyConfig(warmup_days=30))
    result = run_odd_lot_research(data, config, base)
    sale = result.fills[result.fills.side.eq("SELL")].iloc[0]
    next_buy = result.fills[(result.fills.side.eq("BUY")) & (result.fills.symbol.eq("2317.TW"))].iloc[0]
    sale_index = dates.get_loc(sale.timestamp)
    assert next_buy.timestamp == dates[sale_index + 3]
    attempted = result.orders[(result.orders.symbol == "2317.TW") &
                              (result.orders.timestamp <= dates[sale_index + 2])]
    assert len(attempted) == 3 and attempted.outcome.eq("insufficient_cash").all()
    assert result.equity_curve.loc[dates[sale_index + 2], "cash"] == pytest.approx(99_900)

    truncated = run_odd_lot_research(data, config, base, end=dates[sale_index + 1])
    sale_settlement = truncated.settlements[truncated.settlements.side.eq("SELL")].iloc[0]
    assert pd.isna(sale_settlement.settled_at)
    assert sale_settlement.status == "pending_end_of_data" and sale_settlement.sessions_remaining == 1
    assert truncated.equity_curve.iloc[-1].sale_receivables == pytest.approx(99_900)


def test_split_day_exit_uses_adjusted_reference_and_new_share_units(monkeypatch):
    dates = pd.bdate_range("2024-01-02", periods=45)
    adjusted = pd.DataFrame(100.0, index=dates, columns=["2330.TW", "2317.TW"])
    raw = adjusted.copy()
    raw.loc[dates[40]:, "2330.TW"] = 50.0
    split = adjusted * 0
    split.loc[dates[40], "2330.TW"] = 2.0
    data = MarketData(open=adjusted, close=adjusted, raw_open=raw, raw_close=raw,
                      volume=adjusted * 10_000, stock_splits=split)

    def targets(history, eligible, research, strategy, previous):
        weights = pd.Series(0.0, index=history.columns)
        weights["2330.TW" if len(history) < 40 else "2317.TW"] = 1.0
        return weights.copy(), weights

    monkeypatch.setattr(odd_lot_research, "_targets", targets)
    config = OddLotResearchConfig(strategy="momentum", risk_budget=100_000, max_positions=1,
                                  max_weight=1, rebalance_every=1, fill_fraction=1,
                                  commission_bps=0, min_commission=0, slippage_bps=0,
                                  impact_coefficient=0, max_participation=1)
    base = BacktestConfig(initial_cash=99_900, base_currency="TWD",
                          strategy=StrategyConfig(warmup_days=30))
    result = run_odd_lot_research(data, config, base)
    order = result.orders[(result.orders.timestamp == dates[40]) &
                          (result.orders.symbol == "2330.TW")].iloc[0]
    assert order.side == "SELL" and order.requested_quantity == 999
    assert order.limit_price == 49.5
    fill = result.fills[(result.fills.timestamp == dates[40]) &
                        (result.fills.symbol == "2330.TW")].iloc[0]
    assert fill.quantity == 999 and fill.fill_price == 50.0


def test_sale_fee_above_proceeds_is_reserved_as_payable(monkeypatch):
    dates = pd.bdate_range("2024-01-02", periods=36)
    close = pd.DataFrame(5.0, index=dates, columns=["2330.TW"])
    data = MarketData(open=close, close=close, volume=close * 10_000)

    def targets(history, eligible, research, strategy, previous):
        weight = 0.1 if len(history) == 30 else 0.0
        weights = pd.Series(weight, index=history.columns)
        return weights.copy(), weights

    monkeypatch.setattr(odd_lot_research, "_targets", targets)
    config = OddLotResearchConfig(strategy="momentum", max_positions=1, max_weight=0.1,
                                  rebalance_every=1, fill_fraction=1, commission_bps=0,
                                  min_commission=20, slippage_bps=0, impact_coefficient=0,
                                  max_participation=1)
    base = BacktestConfig(initial_cash=50, base_currency="TWD",
                          strategy=StrategyConfig(warmup_days=30))
    result = run_odd_lot_research(data, config, base)
    sale = result.fills[result.fills.side.eq("SELL")].iloc[0]
    assert sale.gross_value < sale.fees
    row = result.equity_curve.loc[sale.timestamp]
    assert row.sale_payables == pytest.approx(sale.fees - sale.gross_value)
    assert row.settled_cash == pytest.approx(row.cash + row.buy_payables + row.sale_payables)
    assert result.equity_curve.iloc[-1].equity == pytest.approx(result.episodes.pnl.sum() + 50)
