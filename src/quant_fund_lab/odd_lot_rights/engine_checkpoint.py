"""Bind completed engine state to the complete, single-cash authorized account."""
import json
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from ..odd_lot_paper.serialization import decode_state, encode_state
from ..odd_lot_paper.types import OddLotSessionState
from .authorization_archive import AuthorizedRightsAccount
from .types import clock


@dataclass(frozen=True)
class RightsEngineCheckpoint:
    """An after-close engine and rights state, including post-close elections.

    Current cash and owned units must match; receivables, obligations, stops and
    pending exits remain in the immutable engine checkpoint. This boundary is
    not an independent source/risk/NAV transition audit.
    """

    engine: OddLotSessionState
    account: AuthorizedRightsAccount

    def __post_init__(self) -> None:
        if not isinstance(self.engine, OddLotSessionState) or not isinstance(self.account, AuthorizedRightsAccount):
            raise TypeError("rights engine checkpoint requires typed engine and authorized account")
        decode_state(encode_state(self.engine))
        account = self.account
        AuthorizedRightsAccount(account.inventory, account.policy, account.authorizations)
        owned = {}
        for lot in account.inventory.lots:
            owned[lot.security_id] = owned.get(lot.security_id, 0)+lot.units
        if ({key: units for key, units in self.engine.shares if units} != owned
                or Decimal(str(self.engine.cash)) != account.inventory.cash):
            raise ValueError("engine checkpoint cash/holdings differ from authoritative rights account")
        book = account.inventory.book
        if book.through is not None:
            completed = clock(book.through).astimezone(ZoneInfo("Asia/Taipei")).date().isoformat()
            if completed > self.engine.session:
                raise ValueError("engine checkpoint cannot expose future rights history")
        sessions = [json.loads(row.command_json)["terms"]["link"]["session"] for row in book.receipts
                    if json.loads(row.command_json)["kind"] in {"portfolio_session", "portfolio_lot_session"}]
        if sessions and sessions[-1] != self.engine.session:
            raise ValueError("engine checkpoint differs from latest recorded session close")


def validate_checkpoint_extension(previous: RightsEngineCheckpoint, current: RightsEngineCheckpoint) -> None:
    """Preserve completed histories and advance exactly one completed engine day.

    Source prefix, business-event reconstruction, marks and risk transitions are
    additional workflow gates; an intact hash chain cannot establish them.
    """
    before, after = previous.engine, current.engine
    if (after.session <= before.session or after.origin_session != before.origin_session
            or after.session_offset != before.session_offset+1 or previous.account.policy != current.account.policy):
        raise ValueError("rights checkpoint session origin, policy or increment changed")
    old, new = previous.account.inventory, current.account.inventory
    if (old.initial_cash != new.initial_cash or old.initial_lots != new.initial_lots
            or new.book.receipts[:len(old.book.receipts)] != old.book.receipts
            or new.postings[:len(old.postings)] != old.postings
            or current.account.authorizations[:len(previous.account.authorizations)] != previous.account.authorizations):
        raise ValueError("rights checkpoint rewrites its completed financial/authorization prefix")
    appended = [json.loads(row.command_json) for row in new.book.receipts[len(old.book.receipts):]]
    sessions = [row for row in appended if row["kind"] in {"portfolio_session", "portfolio_lot_session"}]
    if len(sessions) != 1 or sessions[0]["terms"]["link"]["session"] != after.session:
        raise ValueError("rights checkpoint needs exactly its newly completed engine-session receipt")
