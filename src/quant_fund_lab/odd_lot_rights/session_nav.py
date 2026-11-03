"""Join audited rights inventory and actual session receivables into one NAV."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal, localcontext
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pandas as pd

from .codec import canonical
from .inventory import RightsInventory
from .inventory_valuation import SecurityMark, value_inventory
from .session_link import _amount, _equal, reconcile_session_portfolio
from .types import clock
from .valuation import RightsMark

if TYPE_CHECKING:
    from ..odd_lot_paper.session import OddLotSessionInput, OddLotSessionResult


@dataclass(frozen=True)
class RightsSessionNAV:
    """Economic assets plus disclosures of amounts already reserved from cash.

    Buy payables and negative-sale fee payables must not reduce NAV again.
    Rights commands after the engine close can change current cash/inventory;
    engine_equity preserves the independently checked, pre-command baseline.
    """

    session: str
    source_action_id: str
    as_of: str
    cash: Decimal
    held_securities: Decimal
    unpaid_rights: Decimal
    pending_claims: Decimal
    sale_receivables: Decimal
    fractional_receivables: Decimal
    buy_payables: Decimal
    sale_fee_payables: Decimal
    settled_cash: Decimal
    engine_equity: Decimal
    nav: Decimal


def value_session_nav(
    account: RightsInventory,
    inputs: OddLotSessionInput,
    result: OddLotSessionResult,
    securities: tuple[SecurityMark, ...],
    rights: tuple[RightsMark, ...],
    *,
    as_of: str,
) -> RightsSessionNAV:
    """Value one recorded session plus later known same-day rights commands.

    Actual engine cash, holdings, fills and settlements are reconciled first.
    Market marks for identities present in engine data must match its raw close.
    New instruments require their own explicit mark; the parent quote and
    subscription price are never substitutes. Source authentication and a frozen
    valuation/participation policy are required separately before real use.
    This pure API neither rewrites the old engine NAV nor commits a SQL session.
    """
    if inputs.config.base_currency != "TWD":
        raise ValueError("rights session NAV currently requires explicit TWD accounting")
    link = reconcile_session_portfolio(inputs, result)
    stamp = clock(as_of)
    if stamp.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat() != link.session:
        raise ValueError("rights NAV must use the recorded session's processing date")
    sessions = [(row, json.loads(row.command_json)) for row in account.book.receipts
                if json.loads(row.command_json)["kind"] in {"portfolio_session", "portfolio_lot_session"}]
    if not sessions or canonical(sessions[-1][1]["terms"]["link"]) != canonical(asdict(link)):
        raise ValueError("rights NAV engine result differs from latest recorded session anchor")
    receipt, _ = sessions[-1]
    inventory = value_inventory(account, securities, rights, as_of=as_of)
    prices = inputs.data.raw_close.iloc[inputs.signal_index+1]

    def price(symbol):
        if symbol not in prices:
            raise ValueError("rights NAV lacks the engine security's raw close")
        value = _amount(float(prices[symbol]))
        if value <= 0:
            raise ValueError("rights NAV requires a positive engine raw close")
        codes = inputs.data.currency_codes
        observed = (str(codes.iloc[inputs.signal_index+1][symbol]) if codes is not None
                    else "TWD" if symbol.endswith((".TW", ".TWO")) else None)
        if observed != "TWD":
            raise ValueError("rights NAV raw close requires an explicit TWD security mark")
        return value

    with localcontext() as context:
        context.prec = 80
        for mark in securities:
            if mark.security_id in prices and mark.unit_value != price(mark.security_id):
                raise ValueError("held security mark differs from session raw close")
        fractional = Decimal(0)
        for claim in result.runtime.receivables:
            if (claim.local_currency != "TWD"
                    or pd.Timestamp(claim.settlement_date).date().isoformat() <= link.session
                    or not 0 < _amount(claim.fractional_quantity) < 1):
                raise ValueError("rights NAV fractional receivable currency/timing/units invalid")
            codes = inputs.data.currency_codes
            observed = (str(codes.iloc[inputs.signal_index+1][claim.symbol]) if codes is not None
                        else "TWD" if claim.symbol.endswith((".TW", ".TWO")) else None)
            if observed != "TWD":
                raise ValueError("rights NAV fractional receivable mark currency differs")
            fractional += _amount(claim.fractional_quantity)*price(claim.symbol)
        _equal("fractional receivable mark", result.runtime.portfolio.receivable_value, fractional)
        _equal("NAV fractional receivable mark", result.nav["receivable_value"], fractional)
        held_before_rights = sum((units*price(symbol) for symbol, units in link.shares_after), Decimal(0))
        engine_equity = link.cash_after+held_before_rights+fractional+link.unsettled_sales
        _equal("engine equity", result.nav["equity"], engine_equity)
        buys = _amount(result.nav["buy_payables"])
        fees = _amount(result.nav["sale_payables"])
        return RightsSessionNAV(link.session, receipt.action_id, as_of,
            inventory.cash, inventory.held_assets, inventory.unpaid_rights, inventory.pending_claims,
            link.unsettled_sales, fractional, buys, fees, inventory.cash+buys+fees,
            engine_equity, inventory.nav+link.unsettled_sales+fractional)
