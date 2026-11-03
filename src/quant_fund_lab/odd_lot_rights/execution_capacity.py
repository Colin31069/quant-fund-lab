"""Derive opening sale capacity from audited, post-event security lots."""
from ..odd_lot_paper.sale_limits import OpeningSaleLimits
from .inventory import RightsInventory


def opening_sale_limits(account: RightsInventory, session: str) -> OpeningSaleLimits:
    """Evaluate disclosed release dates at this opening, not the prior close.

    Account lots must describe ownership after any corporate actions before
    execution. This function does not transform lots for splits, conversions or
    terminal events; their event adapter must post those changes first. The
    opening executor verifies the resulting capacities against actual holdings.
    No future price or future command is read to decide a known release date.
    """
    RightsInventory(account.initial_cash, account.initial_lots, account.book,
                    account.lots, account.postings)
    securities = sorted({row.security_id for row in account.lots})
    return OpeningSaleLimits(session, tuple(
        (security, account.tradable_units(security, session)) for security in securities))
