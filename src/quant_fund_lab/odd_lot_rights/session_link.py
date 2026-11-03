"""Reconcile the existing session engine before admitting its cash/holding transfer."""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from ..odd_lot_paper.session import OddLotSessionInput, OddLotSessionResult


@dataclass(frozen=True)
class SessionPortfolioLink:
    """Verified session close boundary, not an extra cash account or source attestation."""

    session: str
    cash_before: Decimal
    cash_after: Decimal
    cash_delta: Decimal
    shares_before: tuple[tuple[str, int], ...]
    shares_after: tuple[tuple[str, int], ...]
    interest: Decimal
    event_cash: Decimal
    execution_cash: Decimal
    settled_sales: Decimal
    unsettled_sales: Decimal


def _amount(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError("session link requires finite numeric financial evidence")
    return Decimal(str(value))


def _equal(label,actual,expected):
    value = _amount(actual)
    if abs(value-expected) > Decimal("0.000001")+Decimal("0.000000000001")*max(abs(value),abs(expected)):
        raise ValueError("session link "+label+" does not reconcile")


def _shares(values):
    if any(not isinstance(symbol,str) or not symbol or type(units) is not int or units < 0
           for symbol,units in values.items()):
        raise ValueError("session link requires explicit nonnegative integer holdings")
    return tuple(sorted((symbol,units) for symbol,units in values.items() if units))


def reconcile_session_portfolio(inputs: OddLotSessionInput,
                                 result: OddLotSessionResult) -> SessionPortfolioLink:
    """Reconstruct current supported engine cash and holdings without execution calls.

    Buy obligations are already reserved; only positive sales newly settled at
    this close add cash. Fee-shortfall sales reduce cash on their trade day and
    are not deducted again at settlement. These equations validate a bridge
    boundary; they do not yet apply rights or authenticate external market data.
    """
    i = inputs.signal_index
    dates = inputs.data.close.index
    previous,session = dates[i],dates[i+1]
    if pd.Timestamp(result.nav["timestamp"]) != session:
        raise ValueError("session link NAV date differs from input boundary")
    before,after = inputs.runtime.portfolio,result.runtime.portfolio
    shares_before = _shares(before.shares)
    shares = dict(shares_before)
    with localcontext() as context:
        context.prec = 80
        initial = _amount(before.cash)
        interest = initial*_amount(inputs.config.cash_annual_yield)*(session.date()-previous.date()).days/365
        event_cash,execution_cash,settled_sales = Decimal(0),Decimal(0),Decimal(0)
        for row in result.actions:
            if pd.Timestamp(row["timestamp"]) != session:
                raise ValueError("session link corporate action date differs")
            symbol,kind = row["symbol"],row["action"]
            if row["quantity_before"] != shares.get(symbol,0):
                raise ValueError("session link corporate action ownership differs")
            if kind == "stock_split":
                exact = Decimal(shares.get(symbol,0))*_amount(row["ratio_or_amount"])
                expected = math.floor(exact+Decimal("0.000000000001"))
                if row["quantity_after"] != expected:
                    raise ValueError("session link split shares differ")
                shares[symbol] = expected
            elif kind not in {"cash_dividend","cash_in_lieu_settlement"}:
                raise ValueError("session link unsupported corporate action")
            event_cash += _amount(row["cash_value"])
        for row in result.terminal_events:
            if pd.Timestamp(row["timestamp"]) != session or row["quantity"] != shares.get(row["symbol"],0):
                raise ValueError("session link terminal date or ownership differs")
            event_cash += _amount(row["proceeds"])
            shares.pop(row["symbol"],None)
        caps = None
        if inputs.sale_limits is not None:
            # Reconstruct the cap check independently of the opening executor.
            caps = dict(inputs.sale_limits.units)
            owned = dict(_shares(shares))
            if (inputs.sale_limits.session != str(session.date()) or set(caps) != set(owned)
                    or any(caps[key] > value for key,value in owned.items())):
                raise ValueError("session link sale limits differ from post-event ownership")
        generated = []
        for row in result.fills:
            if pd.Timestamp(row["timestamp"]) != session:
                raise ValueError("session link fill date differs")
            units,symbol,side = row["quantity"],row["symbol"],row["side"]
            if type(units) is not int or units <= 0 or side not in {"BUY","SELL"}:
                raise ValueError("session link fill quantity or side invalid")
            gross,fees = _amount(row["gross_value"]),_amount(row["fees"])
            if gross < 0 or fees < 0:
                raise ValueError("session link gross or fees invalid")
            _equal("fill gross",row["gross_value"],_amount(row["fill_price"])*units)
            if side == "BUY":
                amount = gross+fees
                execution_cash -= amount
                shares[symbol] = shares.get(symbol,0)+units
            else:
                amount = gross-fees
                if caps is not None:
                    if units > caps.get(symbol,0):
                        raise ValueError("session link fill exceeds opening sale capacity")
                    caps[symbol] -= units
                if units > shares.get(symbol,0):
                    raise ValueError("session link sale exceeds owned units")
                shares[symbol] -= units
                execution_cash += min(Decimal(0),amount)
            generated.append((symbol,side,amount))
        rows = result.runtime.settlements
        old = inputs.runtime.settlements
        if len(rows) != len(old)+len(generated):
            raise ValueError("session link settlement inventory differs from fills")
        for index,row in enumerate(rows):
            if index < len(old):
                baseline = old[index]
                if any(row[key] != baseline[key] for key in ("trade_date","symbol","side","amount","due_session_index")):
                    raise ValueError("session link prior settlement changed")
                settled_before = baseline["settled_at"]
            else:
                symbol,side,amount = generated[index-len(old)]
                if (row["symbol"] != symbol or row["side"] != side
                        or pd.Timestamp(row["trade_date"]) != session or row["due_session_index"] != i+3):
                    raise ValueError("session link fill settlement identity differs")
                _equal("fill settlement amount",row["amount"],amount)
                settled_before = None
            due = settled_before is None and row["due_session_index"] == i+1
            expected_settled = session if due else settled_before
            if row["settled_at"] != expected_settled:
                raise ValueError("session link settlement completion timing differs")
            if due and row["side"] == "SELL" and _amount(row["amount"]) >= 0:
                settled_sales += _amount(row["amount"])
        outstanding = [row for row in rows if row["settled_at"] is None]
        unsettled = sum((_amount(row["amount"]) for row in outstanding
            if row["side"] == "SELL" and row["amount"] >= 0),Decimal(0))
        buys = sum((_amount(row["amount"]) for row in outstanding if row["side"] == "BUY"),Decimal(0))
        shortfalls = sum((-_amount(row["amount"]) for row in outstanding
            if row["side"] == "SELL" and row["amount"] < 0),Decimal(0))
        expected_cash = initial+interest+event_cash+execution_cash+settled_sales
        _equal("portfolio cash",after.cash,expected_cash)
        _equal("NAV cash",result.nav["cash"],expected_cash)
        _equal("settled cash disclosure",result.nav["settled_cash"],expected_cash+buys+shortfalls)
        _equal("sale receivables",result.nav["sale_receivables"],unsettled)
        _equal("buy payables",result.nav["buy_payables"],buys)
        _equal("sale fee payables",result.nav["sale_payables"],shortfalls)
        shares_after = _shares(after.shares)
        if _shares(shares) != shares_after:
            raise ValueError("session link resulting holdings differ from recorded business events")
        actual_cash = _amount(after.cash)
        return SessionPortfolioLink(str(session.date()),initial,actual_cash,actual_cash-initial,
            shares_before,shares_after,interest,event_cash,execution_cash,settled_sales,unsettled)
