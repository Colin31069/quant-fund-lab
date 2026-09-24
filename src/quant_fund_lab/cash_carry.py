from __future__ import annotations

import math

import pandas as pd

from .execution import PortfolioState


def accrue_base_cash_interest(
    state: PortfolioState,
    previous_close: pd.Timestamp,
    next_open: pd.Timestamp,
    annual_yield: float,
) -> float:
    """Credit ACT/365 simple interest on prior-close *spendable base-currency cash*.

    Receivables and positions never accrue cash yield. The interval ends immediately
    before next-open corporate actions and order execution, so newly settled cash
    or dividends cannot earn interest for days before they became spendable.
    """

    rate = float(annual_yield)
    if not math.isfinite(rate) or not 0.0 <= rate <= 1.0:
        raise ValueError("cash_annual_yield must be finite and between 0 and 1")
    days = (
        pd.Timestamp(next_open).date() - pd.Timestamp(previous_close).date()
    ).days
    if days <= 0:
        raise ValueError("cash-interest dates must advance by at least one calendar day")
    if not math.isfinite(state.cash) or state.cash < -1e-9:
        raise ValueError("cash-interest calculation requires nonnegative finite cash")
    if rate == 0.0 or state.cash <= 0.0:
        return 0.0

    interest = float(state.cash * rate * days / 365.0)
    state.cash += interest
    return interest
