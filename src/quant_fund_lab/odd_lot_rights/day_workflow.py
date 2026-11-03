"""One pure entry point for engine close, rights commands and next-state projection."""
from __future__ import annotations

from dataclasses import dataclass

from ..odd_lot_paper.session import OddLotSessionInput
from ..odd_lot_paper.types import StopState
from .authorization_archive import AuthorizedRightsAccount
from .close_commands import RightsCloseCommand, apply_close_commands
from .conversion_risk import ReceiptRiskTransfer
from .lot_events import LotRoundingPolicy, OpeningLotEvent
from .lot_flow import run_and_post_lot_session
from .lot_session import ProjectedLotSession
from .session_projection import RightsSessionProjection, project_rights_session


@dataclass(frozen=True)
class RightsDayRequest:
    account: AuthorizedRightsAccount
    inputs: OddLotSessionInput
    events: tuple[OpeningLotEvent, ...]
    lot_policy: LotRoundingPolicy
    action_id: str
    opening_at: str
    close_at: str
    available_at: str
    evidence_sha256: tuple[str, ...]
    commands: tuple[RightsCloseCommand, ...]
    projection_at: str
    opening_stops: tuple[StopState, ...] = ()
    conversion_risks: tuple[ReceiptRiskTransfer, ...] = ()
    recorded_before: AuthorizedRightsAccount | None = None


@dataclass(frozen=True)
class RightsDayResult:
    account: AuthorizedRightsAccount
    execution: ProjectedLotSession
    projection: RightsSessionProjection
    applied: bool


def advance_rights_day(request: RightsDayRequest) -> RightsDayResult:
    """Execute one ordered day and return one complete account/checkpoint value.

    The caller supplies authenticated opening facts, frozen policy and explicit
    after-close commands. This conservative phase cannot represent an earlier
    same-day bank deadline. SQL atomicity, durable source binding and actual
    issuer admission are separate gates; there is no broker or order I/O here.
    """
    if not isinstance(request, RightsDayRequest):
        raise TypeError("rights workflow requires a typed day request")
    account = request.account
    AuthorizedRightsAccount(account.inventory, account.policy, account.authorizations)
    before = request.recorded_before
    if before is not None and (not isinstance(before, AuthorizedRightsAccount) or before.policy != account.policy):
        raise ValueError("rights day replay prefix differs from its frozen authorization policy")
    if before is not None:
        AuthorizedRightsAccount(before.inventory, before.policy, before.authorizations)
    posted = run_and_post_lot_session(account.inventory, request.events, request.lot_policy,
        request.inputs, request.action_id, opening_at=request.opening_at, as_of=request.close_at,
        available_at=request.available_at, evidence_sha256=request.evidence_sha256,
        recorded_before=None if before is None else before.inventory)
    joined = (account if posted.account is account.inventory else
              AuthorizedRightsAccount(posted.account, account.policy, account.authorizations))
    completed = apply_close_commands(joined, request.action_id, request.commands)
    inputs = request.inputs
    index = inputs.signal_index+1
    dates = inputs.data.close.index
    projection = project_rights_session(completed.inventory, posted.execution.result.runtime,
        completed_session=str(dates[index].date()), origin_session=str(dates[inputs.origin_index].date()),
        session_offset=index-inputs.origin_index, completed_index=index, as_of=request.projection_at,
        opening_stops=request.opening_stops, conversion_risks=request.conversion_risks)
    return RightsDayResult(completed, posted.execution, projection, posted.applied or completed is not account)
