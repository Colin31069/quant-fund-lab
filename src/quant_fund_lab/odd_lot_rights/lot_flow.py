"""Execute and post corporate lots, trades and one authoritative cash atomically."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal

import pandas as pd

from ..odd_lot_paper.session import OddLotSessionInput
from .inventory import RightsInventory, post_rights_transition
from .lot_close import LotSessionFill, close_session_lots
from .lot_events import LotRoundingPolicy, OpeningLotEvent
from .lot_session import ProjectedLotSession, run_lot_projected_session
from .session_link import reconcile_session_portfolio
from .transitions import ZERO, _begin, _finish
from .types import RightsTransition, SecurityCredit, SecurityDebit, evidence


@dataclass(frozen=True)
class PostedLotSession:
    account: RightsInventory
    execution: ProjectedLotSession
    applied: bool


def _prior(account, action_id, recorded_before):
    old = next((i for i, row in enumerate(account.book.receipts) if row.action_id == action_id), None)
    if old is None:
        if recorded_before is not None:
            raise ValueError("recorded lot-session prefix has no completed receipt")
        return account
    if recorded_before is None:
        raise ValueError("lot-session replay requires its original recorded account prefix")
    if not isinstance(recorded_before, RightsInventory):
        raise TypeError("lot-session recorded prefix requires a typed inventory")
    RightsInventory(recorded_before.initial_cash, recorded_before.initial_lots, recorded_before.book,
                    recorded_before.lots, recorded_before.postings)
    ids = {row.action_id for row in account.book.receipts[:old]}
    if (recorded_before.initial_cash != account.initial_cash
            or recorded_before.initial_lots != account.initial_lots
            or recorded_before.book.receipts != account.book.receipts[:old]
            or recorded_before.postings != tuple(row for row in account.postings if row[0] in ids)):
        raise ValueError("lot-session recorded account prefix differs from completed history")
    return recorded_before


def _same_result(left, right):
    return (left.runtime == right.runtime and pd.Series(left.nav).equals(pd.Series(right.nav))
            and all(pd.DataFrame(getattr(left, name)).equals(pd.DataFrame(getattr(right, name)))
                    for name in ("signals", "orders", "fills", "actions", "terminal_events")))


def post_projected_lot_session(account: RightsInventory, execution: ProjectedLotSession,
                               inputs: OddLotSessionInput, action_id: str,
                               events: tuple[OpeningLotEvent, ...], policy: LotRoundingPolicy,
                               *, opening_at: str, as_of: str, available_at: str,
                               evidence_sha256: tuple[str, ...],
                               recorded_before: RightsInventory | None = None) -> RightsInventory:
    """Post the exact current-prefix engine execution and its corporate lot plan.

    The public run/post wrapper below reconstructs the execution. This lower
    boundary independently reconciles engine cash/holdings and rejects forged
    lot journal results before publishing any account value. Source evidence
    authenticity and durable SQL atomicity remain outer workflow requirements.
    """
    evidence(available_at, evidence_sha256)
    prior = _prior(account, action_id, recorded_before)
    expected = run_lot_projected_session(prior, events, policy, inputs, as_of=opening_at)
    if (execution.projection != expected.projection
            or not _same_result(execution.result, expected.result)):
        raise ValueError("lot execution differs from reconstructed source session")
    result = execution.result
    bound = replace(inputs, sale_limits=execution.projection.sale_limits)
    link = reconcile_session_portfolio(bound, result)
    fills = tuple(LotSessionFill(row["symbol"], row["side"], row["quantity"],
        Decimal(str(row["fill_price"])), Decimal(str(row["gross_value"])), Decimal(str(row["fees"])))
        for row in result.fills)
    final = close_session_lots(execution.projection.lots, fills, action_id, link.session)
    journal = {"opening_at": opening_at, "policy": asdict(policy),
        "events": [asdict(row) for row in events], "initial_lots": [asdict(row) for row in prior.lots],
        "final_lots": [asdict(row) for row in final], "fills": [asdict(row) for row in fills]}
    terms = {"available_at": available_at, "evidence_sha256": evidence_sha256,
             "link": asdict(link), "lot_journal": journal}
    started = _begin(account.book, action_id, as_of, {"kind": "portfolio_lot_session", "terms": terms})
    if started is None:
        return post_rights_transition(account, RightsTransition(account.book, action_id, ZERO, applied=False))
    identity, _ = started
    debits = tuple(SecurityDebit(row.right_key, row.security_id, row.units) for row in account.lots)
    credits = tuple(SecurityCredit(row.right_key, row.security_id, row.units, row.tradable_session) for row in final)
    transition = _finish(account.book, action_id, as_of, identity, account.book.positions,
                         link.cash_after, credits, debits)
    return post_rights_transition(account, transition)


def run_and_post_lot_session(account: RightsInventory, events: tuple[OpeningLotEvent, ...],
                              policy: LotRoundingPolicy, inputs: OddLotSessionInput,
                              action_id: str, *, opening_at: str, as_of: str,
                              available_at: str, evidence_sha256: tuple[str, ...],
                              recorded_before: RightsInventory | None = None) -> PostedLotSession:
    """Return execution and joined inventory only after every reconstruction passes."""
    prior = _prior(account, action_id, recorded_before)
    execution = run_lot_projected_session(prior, events, policy, inputs, as_of=opening_at)
    posted = post_projected_lot_session(account, execution, inputs, action_id, events, policy,
        opening_at=opening_at, as_of=as_of, available_at=available_at, evidence_sha256=evidence_sha256,
        recorded_before=recorded_before)
    return PostedLotSession(posted, execution, posted is not account)
