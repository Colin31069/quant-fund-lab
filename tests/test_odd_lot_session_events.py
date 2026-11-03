"""Event-boundary checkpoint comparisons use independent cash and share equations."""
from dataclasses import replace

import pandas as pd
import pytest

from quant_fund_lab.config import BacktestConfig
from quant_fund_lab.data import MarketData
from quant_fund_lab.execution import PortfolioState, prior_session_liquidity
from quant_fund_lab.odd_lot_paper.bridge import (
    HistoricalSessionState,
    capture_session_state,
    restore_session_state,
)
from quant_fund_lab.odd_lot_paper.engine_records import EngineStop
from quant_fund_lab.odd_lot_paper.serialization import decode_state, encode_state
from quant_fund_lab.odd_lot_paper.session import OddLotSessionInput, run_odd_lot_session
from quant_fund_lab.odd_lot_research import OddLotResearchConfig, odd_lot_backtest_config


def _fixture():
    dates = pd.bdate_range("2024-01-02", periods=5)
    raw = pd.DataFrame({"2330.TW": [100., 196., 196., 196., 196.]}, index=dates)
    splits, dividends = raw * 0 + 1, raw * 0
    splits.iloc[1, 0], dividends.iloc[1, 0] = .5, 2.
    prices = raw * float("nan")
    prices.iloc[3, 0] = 200.
    availability = pd.DataFrame(pd.NaT, index=dates, columns=raw.columns)
    availability.iloc[1, 0] = dates[3]
    data = MarketData(raw, raw, raw * 100000, raw_open=raw, raw_close=raw,
        stock_splits=splits, dividends=dividends, cash_in_lieu_prices=prices,
        cash_in_lieu_settlement_dates=availability)
    runtime = HistoricalSessionState(PortfolioState(100., {"2330.TW": 3}),
        {"2330.TW": EngineStop(90., 100., .1)}, {}, set(), [], [
            {"trade_date": dates[0], "symbol": "2330.TW", "side": side,
             "amount": amount, "settled_at": None, "due_session_index": 2}
            for side, amount in (("SELL", 20.), ("BUY", 15.))], True)
    research = OddLotResearchConfig(strategy="equal_weight")
    config = odd_lot_backtest_config(BacktestConfig(initial_cash=100., base_currency="TWD"), research)
    return OddLotSessionInput(runtime, data, research, config, 0, 0, prior_session_liquidity(data.volume))


def test_split_dividend_receivable_and_trade_settlement_survive_each_checkpoint():
    inputs = _fixture()
    runtime = inputs.runtime
    cash = []
    equity = []
    action_types = []
    for index in range(4):
        actual = run_odd_lot_session(replace(inputs, runtime=runtime, signal_index=index))
        checkpoint = capture_session_state(runtime, session=str(inputs.data.close.index[index].date()),
            origin_session=str(inputs.data.close.index[0].date()), session_offset=index, completed_index=index)
        restored = restore_session_state(decode_state(encode_state(checkpoint)), completed_index=index)
        resumed = run_odd_lot_session(replace(inputs, runtime=restored, signal_index=index))
        assert actual.nav == resumed.nav
        pd.testing.assert_frame_equal(pd.DataFrame(actual.actions), pd.DataFrame(resumed.actions), check_exact=True)
        cash.append(actual.nav["cash"])
        equity.append(actual.nav["equity"])
        action_types.extend(row["action"] for row in actual.actions)
        runtime = actual.runtime
    assert cash == [106., 126., 226., 226.]
    assert equity == [420., 420., 422., 422.]
    assert runtime.portfolio.shares == {"2330.TW": 1} and not runtime.receivables
    assert action_types.count("cash_dividend") == action_types.count("stock_split") == 1
    assert sum("settlement" in action for action in action_types) == 1
    assert inputs.runtime.portfolio.cash == 100 and inputs.runtime.portfolio.shares["2330.TW"] == 3


def test_missing_required_fractional_price_rolls_back_whole_transition_in_memory():
    inputs = _fixture()
    runtime = inputs.runtime
    for index in range(2):
        runtime = run_odd_lot_session(replace(inputs, runtime=runtime, signal_index=index)).runtime
    prices = inputs.data.cash_in_lieu_prices * float("nan")
    invalid = replace(inputs.data, cash_in_lieu_prices=prices)
    with pytest.raises(ValueError, match="settlement price"):
        run_odd_lot_session(replace(inputs, runtime=runtime, data=invalid, signal_index=2))
    assert runtime.portfolio.cash == 126 and len(runtime.receivables) == 1
