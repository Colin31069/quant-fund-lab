"""Authenticated future virtual accounts; no broker API or real order path exists."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from ..odd_lot_inputs.types import PriceSourcePolicy
from ..odd_lot_protocol.build import verify_candidate_binding
from ..odd_lot_research import OddLotResearchConfig
from ..odd_lot_study import _backtest_config, _subset, load_frozen_odd_lot_study
from . import observation_gate
from .forward_binding import ForwardReplayBinding
from .observation_auth import authenticate_observation_plan
from .replay import ReplayIdentity, ReplayResult, _replay_account
from .source_archive import publish_source_archive


@dataclass(frozen=True)
class ObservationAccountResult:
    plan_id: str
    status: str
    requested_through: str
    reasons: tuple[str, ...]
    replay: ReplayResult | None

    def __post_init__(self) -> None:
        if (self.status not in {"pending", "blocked", "active"}
                or (self.status == "active" and (self.replay is None or self.reasons))
                or (self.status != "active" and not self.reasons)):
            raise ValueError("observation status differs from replay/readiness evidence")


def _check_source_policy(metadata: dict, provider_directory: str | Path | None,
                         policy: PriceSourcePolicy | None) -> None:
    if metadata["data_source"] == "twse_official":
        if provider_directory is not None or policy is not None:
            raise ValueError("observation source policy differs from official-only candidate")
    elif metadata["data_source"] == "provider_reviewed":
        if provider_directory is None or policy is None:
            raise ValueError("reviewed candidate requires its declared provider selection rule")
        frozen = json.loads(metadata["source_provenance"]["source_policy_json"])
        if any(frozen[key] != getattr(policy, key) for key in ("policy_id", "price_atol", "schema_version")) or (
                tuple(frozen["priority"]) != tuple(policy.priority)):
            raise ValueError("observation provider selection rule differs from registered candidate")
    else:
        raise ValueError("observation requires a source-backed registered candidate")


def run_observation_account(plan_directory: str | Path, *, through: str,
                             registry_path: str | Path, studies_directory: str | Path,
                             source_directory: str | Path, official_directory: str | Path,
                             account_path: str | Path, snapshot_root: str | Path,
                             source_archive_root: str | Path, create: bool = False,
                             provider_directory: str | Path | None = None,
                             price_policy: PriceSourcePolicy | None = None,
                             _fault: Callable[[str], None] | None = None) -> ObservationAccountResult:
    """Activate/continue only verified new sessions, preserving the last complete day.

    Before the planned future start this returns pending without creating files.
    A trailing gap returns blocked and may commit only an earlier fully ready
    prefix. Corrupt/changed sources or account configuration raise without reset.
    Dates and acquisition records never authorize actual orders.
    """
    auth_args = {"registry_path":registry_path,"studies_directory":studies_directory,
                 "source_directory":source_directory}
    authenticated = authenticate_observation_plan(plan_directory, **auth_args)
    plan, protocol = authenticated.plan, authenticated.protocol
    if date.fromisoformat(through).isoformat() != through or through < plan.first_session:
        raise ValueError("observation cutoff must be canonical and at/after the planned start")
    today = observation_gate._now().astimezone(ZoneInfo("Asia/Taipei")).date().isoformat()
    if today < plan.first_session:
        return ObservationAccountResult(plan.plan_id,"pending",through,("planned_start_is_still_future",),None)
    candidate = next(row for row in protocol.candidates if row.candidate_id == plan.candidate_id)
    _, metadata = load_frozen_odd_lot_study(Path(studies_directory) / candidate.study_id)
    verify_candidate_binding(protocol,candidate,metadata)
    _check_source_policy(metadata,provider_directory,price_policy)
    gate_args = {"official_directory":official_directory,"symbols":tuple(protocol.symbols),
                 "benchmark":protocol.benchmark,"provider_directory":provider_directory,"price_policy":price_policy}
    requested = observation_gate.assess_forward_session(plan,through,**gate_args)
    ready = requested if requested.status == "ready" else None
    if ready is None:
        # Each attempt checks the full fixed prefix; no missing middle day is skipped.
        earlier = [str(day.date()) for day in requested.inputs.data.close.index
                   if plan.first_session <= str(day.date()) < through and str(day.date()) <= today]
        for cutoff in reversed(earlier):
            assessment = observation_gate.assess_forward_session(plan,cutoff,**gate_args)
            if assessment.status == "ready":
                ready = assessment
                break
    if ready is None:
        return ObservationAccountResult(plan.plan_id,"blocked",through,requested.reasons,None)
    data = _subset(ready.inputs.data,list(protocol.symbols))
    if data.base_currency not in {None,"TWD"}:
        raise ValueError("forward odd-lot account requires TWD")
    index = int(data.close.index.get_loc(plan.first_session))
    if index < 1:
        raise ValueError("forward account needs a prior signal session")
    origin = data.close.index[index-1].date().isoformat()
    archive = publish_source_archive(ready.inputs,source_archive_root)
    binding = ForwardReplayBinding(plan,ready.evidence,archive,Path(source_archive_root),
        (*tuple(protocol.symbols),protocol.benchmark),price_policy)
    research = replace(OddLotResearchConfig(**json.loads(plan.research_config_json)),strategy=plan.strategy)
    base = _backtest_config(json.loads(plan.execution_config_json))
    identity = ReplayIdentity(protocol.protocol_id,plan.execution_id,ready.evidence.calendar_revision,origin)

    def verify_sources(stage):
        if _fault is not None:
            _fault(stage)
        if authenticate_observation_plan(plan_directory,**auth_args) != authenticated:
            raise ValueError("observation plan or decision changed during execution")
        for name,path in ready.inputs.source_files.items():
            if hashlib.sha256(path.read_bytes()).hexdigest() != ready.inputs.source_hashes[name]:
                raise ValueError("observation source changed during execution: "+name)

    verify_sources("preflight")
    replay = _replay_account(account_path,data,research,base,identity,create=create,
        snapshot_root=snapshot_root,observation=binding,_fault=verify_sources)
    status = "active" if requested.status == "ready" else "blocked"
    return ObservationAccountResult(plan.plan_id,status,through,requested.reasons,replay)
