"""Apply already verified source selection to the shared TWSE event normalizer."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from .types import PriceSelection


def overlay_selected_prices(prices: dict, covered_prices: set, selection: PriceSelection,
                             first: pd.Timestamp, last: pd.Timestamp, *,
                             reviewed_suspensions: frozenset[tuple[pd.Timestamp, str]] = frozenset()) -> list:
    """Replace only the quote input; event, coverage and accounting rules stay shared.

    The caller supplies suspensions loaded through the official evidence gate.
    V2 suppresses only its redundant no-quote finding for an exact individual
    halt with no reported trade activity; the shared normalizer still requires a prior mark and rejects quotes
    on halted days. V1 keeps its original strict findings.
    """
    from ..twse_odd_lot import TWSEIssue

    if (selection.policy.start != str(first.date()) or selection.policy.end != str(last.date())
            or selection.policy.end > selection.policy.cutoff):
        raise ValueError("price selection range differs from evidence preparation")
    for values in prices.values():
        values.clear()
    covered_prices.clear()
    issues = []
    for row in selection.selected:
        if row.symbol not in prices:
            continue
        covered_prices.add((row.symbol, row.date[:7]))
        if row.no_quote:
            if not (selection.policy.accepts_reviewed_symbol_halts
                    and (pd.Timestamp(row.date), row.symbol) in reviewed_suspensions
                    and row.volume_shares == 0 and row.turnover_twd in (None, 0)
                    and row.trades in (None, 0)):
                issues.append(TWSEIssue(row.date, row.date, row.symbol,
                                       "供應商記錄無報價；不能當作停牌或可交易價格"))
        else:
            prices[row.symbol][pd.Timestamp(row.date)] = (row.raw_open, row.raw_close, row.volume_shares)
    for conflict in selection.conflicts:
        if conflict.symbol in prices:
            issues.append(TWSEIssue(conflict.date, conflict.date, conflict.symbol,
                                   "價格來源衝突；需核對原始來源"))
    return issues
