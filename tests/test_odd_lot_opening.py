"""Opening phase hand checks preserve expiry and unavailable sale proceeds."""
from dataclasses import replace

import pandas as pd

from quant_fund_lab.config import BacktestConfig
from quant_fund_lab.execution import PortfolioState
from quant_fund_lab.odd_lot_paper.engine_records import EngineOrder
from quant_fund_lab.odd_lot_paper.opening import OpeningExecutionInput, execute_opening_orders
from quant_fund_lab.odd_lot_research import OddLotResearchConfig, odd_lot_backtest_config


def _inputs(state, orders, *, fraction=1.):
    research = OddLotResearchConfig(strategy="equal_weight", min_commission=0,
        commission_bps=0, slippage_bps=0, impact_coefficient=0,
        fill_fraction=fraction, max_participation=1.)
    config = odd_lot_backtest_config(BacktestConfig(initial_cash=1000, base_currency="TWD"), research)
    return OpeningExecutionInput(state, {}, orders, ("2330.TW", "2317.TW"), research, config,
        pd.Timestamp("2024-01-05"), 3, pd.Series({"2330.TW": 100., "2317.TW": 100.}),
        pd.Series({"2330.TW": 1000000., "2317.TW": 1000000.}),
        pd.Series({"2330.TW": 100., "2317.TW": 100.}))


def test_partial_buy_expires_without_mutating_input_and_creates_reserved_payable():
    state = PortfolioState(1000.)
    order = EngineOrder("BUY", 10, "entry", signal_price=100.)
    inputs = _inputs(state, {"2330.TW": order}, fraction=.5)
    result = execute_opening_orders(inputs)
    assert result.portfolio.cash == 500 and result.portfolio.shares["2330.TW"] == 5
    assert not result.pending and result.orders[0]["status"] == "partial_expired"
    assert result.settlements[0]["amount"] == 500
    assert result.settlements[0]["due_session_index"] == 5
    assert state.cash == 1000 and not state.shares and inputs.pending["2330.TW"] == order


def test_sell_proceeds_cannot_fund_buy_at_same_open_even_when_processed_first():
    inputs = _inputs(PortfolioState(0., {"2330.TW": 5}), {
        "2330.TW": EngineOrder("SELL", 5, "model_exit"),
        "2317.TW": EngineOrder("BUY", 5, "entry", signal_price=100.)})
    # Remove stock sale tax explicitly for the hand calculation.
    rules = {key: {**value, "sell_tax_bps": 0} for key, value in inputs.research.instrument_rules.items()}
    inputs = replace(inputs, research=replace(inputs.research, instrument_rules=rules))
    result = execute_opening_orders(inputs)
    assert len(result.fills) == 1 and result.fills[0]["side"] == "SELL"
    assert result.portfolio.cash == 0 and not result.portfolio.shares.get("2317.TW", 0)
    assert result.settlements[0]["amount"] == 500
    assert [row["side"] for row in result.orders] == ["SELL", "BUY"]
    assert result.orders[-1]["filled_quantity"] == 0 and not result.pending
