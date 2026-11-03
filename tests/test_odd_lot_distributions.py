"""Independent distribution equations and failure atomicity before durable execution."""
import pandas as pd
import pytest

from quant_fund_lab.config import DividendWithholdingConfig
from quant_fund_lab.execution import PortfolioState
from quant_fund_lab.odd_lot_paper.distributions import (
    DistributionInput,
    apply_session_distributions,
)


def test_dividend_uses_pre_split_shares_and_input_portfolio_is_unchanged():
    symbol = "2330.TW"
    state = PortfolioState(100., {symbol: 10})
    inputs = DistributionInput(state, (), pd.Timestamp("2024-01-05"),
        pd.Series({symbol: 2.}), pd.Series({symbol: 2.}), pd.Series({symbol: 49.}), DividendWithholdingConfig())
    result = apply_session_distributions(inputs)
    assert result.portfolio.cash == 120 and result.portfolio.shares[symbol] == 20
    assert result.portfolio.equity(pd.Series({symbol: 49.})) == 1100
    assert state.cash == 100 and state.shares[symbol] == 10
    assert len(result.dividend_events) == len(result.split_events) == 1


def test_split_failure_does_not_leave_dividend_credited_in_input_state():
    symbol = "2330.TW"
    state = PortfolioState(100., {symbol: 10})
    inputs = DistributionInput(state, (), pd.Timestamp("2024-01-05"),
        pd.Series({symbol: 2.}), pd.Series({symbol: .25}),
        pd.Series({symbol: 49.}), DividendWithholdingConfig(),
        cash_in_lieu_prices=pd.Series({symbol: 50.}),
        cash_in_lieu_settlement_dates=pd.Series({symbol: pd.Timestamp("2024-01-10")}))
    with pytest.raises(ValueError, match="future cash-in-lieu"):
        apply_session_distributions(inputs)
    assert state.cash == 100 and state.shares == {symbol: 10}
