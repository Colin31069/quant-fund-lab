"""Checkpoint round-trips between actual single-day transitions preserve business output."""
from dataclasses import replace

import pandas as pd
import pytest

from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.execution import PortfolioState, prior_session_liquidity
from quant_fund_lab.odd_lot_paper.bridge import (
    HistoricalSessionState,
    capture_session_state,
    restore_session_state,
)
from quant_fund_lab.odd_lot_paper.serialization import decode_state, encode_state
from quant_fund_lab.odd_lot_paper.session import OddLotSessionInput, run_odd_lot_session
from quant_fund_lab.odd_lot_research import OddLotResearchConfig, odd_lot_backtest_config


def test_daily_serialized_checkpoints_match_uninterrupted_execution():
    data = synthetic_market_data(("2330.TW", "2317.TW"), periods=65, seed=4)
    research = OddLotResearchConfig(strategy="momentum", momentum_lookback=5)
    config = odd_lot_backtest_config(BacktestConfig(initial_cash=100000, base_currency="TWD",
        strategy=StrategyConfig(warmup_days=30)), research)
    initial = HistoricalSessionState(PortfolioState(100000.), {}, {}, set(), [], [], False)
    liquidity = prior_session_liquidity(data.volume)
    uninterrupted = serialized = initial
    for index in range(29, 64):
        inputs = OddLotSessionInput(uninterrupted, data, research, config, index, 29, liquidity)
        actual = run_odd_lot_session(inputs)
        resumed = run_odd_lot_session(replace(inputs, runtime=serialized))
        assert actual.signals == resumed.signals or pd.DataFrame(actual.signals).equals(pd.DataFrame(resumed.signals))
        for field in ("orders", "fills", "actions", "terminal_events"):
            pd.testing.assert_frame_equal(pd.DataFrame(getattr(actual, field)),
                                          pd.DataFrame(getattr(resumed, field)), check_exact=True)
        assert actual.nav == resumed.nav
        checkpoint = capture_session_state(resumed.runtime, session=str(data.close.index[index+1].date()),
            origin_session=str(data.close.index[29].date()), session_offset=index+1-29,
            completed_index=index+1)
        serialized = restore_session_state(decode_state(encode_state(checkpoint)), completed_index=index+1)
        uninterrupted = actual.runtime
    assert initial.portfolio.cash == 100000 and not initial.portfolio.shares
    with pytest.raises(ValueError, match="following session"):
        run_odd_lot_session(replace(inputs, signal_index=64))
