"""A complete dividend trade reconciles independent arithmetic through T+2."""
from decimal import Decimal

import pandas as pd
import pytest

from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import MarketData
from quant_fund_lab.market_calendar import expected_market_sessions
from quant_fund_lab.odd_lot_research import OddLotResearchConfig, run_odd_lot_research
from quant_fund_lab.twse_odd_lot import _total_return


def test_dividend_slippage_commission_tax_and_settlement_are_each_counted_once(monkeypatch):
    dates = pd.DatetimeIndex(expected_market_sessions("TW", "2024-01-01", "2024-12-31").sessions)[:36]
    symbol = "2330.TW"
    raw = pd.DataFrame(100.0, index=dates, columns=[symbol])
    raw.loc[dates[31]:] = 98.0
    dividends = pd.DataFrame(0.0, index=dates, columns=[symbol])
    dividends.loc[dates[31], symbol] = 2.0
    splits = dividends * 0.0
    adjusted = _total_return(raw, dividends, splits)
    data = MarketData(adjusted.copy(), adjusted, raw * 100000,
                      raw_open=raw.copy(), raw_close=raw, dividends=dividends, stock_splits=splits)
    before = {name: getattr(data, name).copy(deep=True) for name in ("raw_open", "raw_close", "dividends")}

    def targets(history, eligible, research, strategy, previous):
        weight = .1 if len(history) == 30 else 0.0
        return pd.Series(1.0, index=history.columns), pd.Series(weight, index=history.columns)

    monkeypatch.setattr("quant_fund_lab.odd_lot_research._targets", targets)
    research = OddLotResearchConfig(strategy="momentum", risk_budget=1000000,
        max_positions=1, max_weight=.1, rebalance_every=1,
        min_stop_distance=.2, max_stop_distance=.2, min_commission=0,
        commission_bps=10, slippage_bps=10, impact_coefficient=0,
        max_participation=1, fill_fraction=1, fee_rounding="fractional",
        instrument_rules={symbol: {"kind": "stock", "sell_tax_bps": 30, "price_limit_pct": None}})
    base = BacktestConfig(initial_cash=100000, base_currency="TWD", strategy=StrategyConfig(warmup_days=30))
    result = run_odd_lot_research(data, research, base)

    # Independent decimal arithmetic includes adverse tick rounding: buy 100.1 -> 100.5,
    # sell 97.902 -> 97.9. No matching/fee/settlement helper is used as an oracle.
    buy_gross, buy_commission = Decimal(10050), Decimal("10.05")
    sell_gross, sell_commission, tax = Decimal(9790), Decimal("9.79"), Decimal("29.37")
    dividend = Decimal(200)
    proceeds = sell_gross - sell_commission - tax
    net = proceeds + dividend - buy_gross - buy_commission
    cash_before_sale_settlement = Decimal(100000) - buy_gross - buy_commission + dividend
    final_cash = Decimal(100000) + net
    assert net == Decimal("-109.21") and final_cash == Decimal("99890.79")
    assert list(result.fills.side) == ["BUY", "SELL"]
    assert list(result.fills.quantity) == [100, 100]
    assert list(result.fills.timestamp) == [dates[30], dates[31]]
    assert list(result.fills.fill_price) == pytest.approx([100.5, 97.9])
    assert list(result.fills.commission) == pytest.approx([float(buy_commission), float(sell_commission)])
    assert list(result.fills.sell_tax) == pytest.approx([0, float(tax)])
    assert list(result.fills.slippage_cost) == pytest.approx([50, 10])
    action = result.corporate_actions.query("action == 'cash_dividend'")
    assert len(action) == 1 and action.cash_value.sum() == float(dividend)
    assert len(result.episodes) == 1 and result.episodes.iloc[0].status == "closed"
    assert result.episodes.iloc[0].pnl == pytest.approx(float(net))
    curve = result.equity_curve
    for date in dates[31:33]:
        assert curve.loc[date, "cash"] == pytest.approx(float(cash_before_sale_settlement))
        assert curve.loc[date, "sale_receivables"] == pytest.approx(float(proceeds))
        assert curve.loc[date, "equity"] == pytest.approx(float(final_cash))
    assert curve.loc[dates[32], "buy_payables"] == 0
    for date in dates[33:]:
        assert curve.loc[date, "cash"] == pytest.approx(float(final_cash))
        assert curve.loc[date, "sale_receivables"] == 0
        assert curve.loc[date, "equity"] == pytest.approx(float(final_cash))
    sale = result.settlements.query("side == 'SELL'")
    assert len(sale) == 1 and sale.iloc[0].settled_at == dates[33]
    assert sale.iloc[0].amount == pytest.approx(float(proceeds))
    for name, frame in before.items():
        pd.testing.assert_frame_equal(getattr(data, name), frame)
