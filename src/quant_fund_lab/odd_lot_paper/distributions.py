"""Pure portfolio distribution phase: dividend before simultaneous split."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

import pandas as pd

from ..config import DividendWithholdingConfig
from ..corporate_actions import (
    CashInLieuReceivable,
    CorporateActionEvent,
    apply_cash_dividend_events,
    apply_stock_split_events,
)
from ..execution import PortfolioState


@dataclass(frozen=True)
class DistributionInput:
    portfolio: PortfolioState
    receivables: tuple[CashInLieuReceivable, ...]
    session: pd.Timestamp
    dividends: pd.Series
    splits: pd.Series
    raw_open: pd.Series
    withholding: DividendWithholdingConfig
    currency_codes: pd.Series | None = None
    market_codes: pd.Series | None = None
    cash_in_lieu_prices: pd.Series | None = None
    cash_in_lieu_settlement_dates: pd.Series | None = None


@dataclass(frozen=True)
class DistributionResult:
    portfolio: PortfolioState
    receivables: tuple[CashInLieuReceivable, ...]
    dividend_events: tuple[CorporateActionEvent, ...]
    split_events: tuple[CorporateActionEvent, ...]


def apply_session_distributions(inputs: DistributionInput) -> DistributionResult:
    """Compute a fresh state; exceptions never partially mutate caller accounting."""
    state = PortfolioState(inputs.portfolio.cash, dict(inputs.portfolio.shares),
                           inputs.portfolio.receivable_value)
    receivables = deepcopy(list(inputs.receivables))
    dividends = apply_cash_dividend_events(
        state, inputs.dividends, inputs.session, withholding=inputs.withholding,
        market_codes=inputs.market_codes, currency_codes=inputs.currency_codes)
    splits = apply_stock_split_events(
        state, inputs.splits, inputs.raw_open, inputs.session,
        currency_codes=inputs.currency_codes, cash_in_lieu_prices=inputs.cash_in_lieu_prices,
        cash_in_lieu_settlement_dates=inputs.cash_in_lieu_settlement_dates,
        receivables=receivables)
    return DistributionResult(state, tuple(receivables), tuple(dividends), tuple(splits))
