"""Authenticate catalog history against an actual registered source-backed study."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

import pandas as pd

from ..execution import prior_session_liquidity
from ..odd_lot_protocol.build import verify_candidate_binding
from ..odd_lot_protocol.provenance import capture_execution_identity
from ..odd_lot_protocol.registry_read import ReadOnlyExperimentRegistry
from ..odd_lot_protocol.storage import load_protocol
from ..odd_lot_research import OddLotResearchConfig, odd_lot_backtest_config
from ..odd_lot_study import _backtest_config, _subset, load_frozen_odd_lot_study
from .codec import canonical, fingerprint
from .day_request_archive import load_day_archive
from .durable_day_workflow import day_input_sha256
from .request_catalog import RightsRequestCatalog
from .request_values_codec import encode_value


@dataclass(frozen=True)
class RegisteredRightsSource:
    protocol_directory: Path
    registry_path: Path
    studies_directory: Path
    source_directory: Path
    candidate_id: str
    period: str
    strategy: str


@dataclass(frozen=True)
class RegisteredRightsAssessment:
    protocol_id: str
    candidate_id: str
    study_id: str
    period: str
    purpose: str
    archives_checked: int
    scope: str = "registered_source_backed_historical_no_unverified_rights_commands"


def authenticate_registered_catalog(binding: RegisteredRightsSource, catalog: RightsRequestCatalog,
                                     requests_directory: str | Path) -> RegisteredRightsAssessment:
    """Read original registry, protocol and raw-backed study; create no account.

    Existing study protocols do not declare new rights participation/marks or
    authenticate issuer-term adapters. This boundary therefore rejects supplied
    close commands and conversion-risk mappings until those additional contracts
    exist. It never converts a historical run into approved forward observation.
    """
    if not isinstance(binding, RegisteredRightsSource):
        raise TypeError("registered rights source requires a typed binding")
    source = Path(binding.source_directory).resolve()
    if Path(__file__).resolve().parents[1] != source/"src/quant_fund_lab":
        raise ValueError("registered rights source differs from the executing package")
    protocol = load_protocol(binding.protocol_directory)
    execution = capture_execution_identity(source)
    if protocol.execution != execution or catalog.config.execution_sha256 != execution.identity:
        raise ValueError("registered rights execution identity differs from frozen source")
    if catalog.config.protocol_sha256 != protocol.protocol_id:
        raise ValueError("rights catalog names a different study protocol")
    with ReadOnlyExperimentRegistry(binding.registry_path) as registry:
        if registry.get_protocol(protocol.protocol_id) != protocol:
            raise ValueError("registered rights protocol differs from its original registry")
    candidate = next((row for row in protocol.candidates if row.candidate_id == binding.candidate_id), None)
    period = next((row for row in protocol.periods if row.name == binding.period), None)
    if candidate is None or period is None:
        raise ValueError("registered rights run requires a declared candidate and period")
    if period.purpose == "forward_observation" or period.data_access == "unseen":
        raise ValueError("registered historical rights entry cannot activate forward observation")
    if binding.strategy not in {"ensemble", "momentum", "equal_weight"}:
        raise ValueError("registered rights strategy is outside the historical engine plan")
    study = Path(binding.studies_directory)/candidate.study_id
    data, metadata = load_frozen_odd_lot_study(study)
    verify_candidate_binding(protocol, candidate, metadata)
    ready = next(row for row in metadata["readiness"]["periods"] if row["period"] == period.name)
    if ready["status"] != "ready" or metadata["data_source"] not in {"twse_official", "provider_reviewed"}:
        raise ValueError("registered rights candidate period requires ready source-backed inputs")
    calendar = fingerprint(ready["warmup"]["calendar_revision"])
    if catalog.config.calendar_sha256 != calendar:
        raise ValueError("registered rights calendar identity differs from source readiness")
    research = replace(OddLotResearchConfig(**metadata["research_config"]), strategy=binding.strategy)
    base = _backtest_config(metadata["backtest_config"])
    config = odd_lot_backtest_config(base, research)
    reference = _subset(data, list(protocol.symbols))
    start = int(data.close.index.searchsorted(pd.Timestamp(period.start)))
    if start < protocol.warmup or start >= len(data.close.index):
        raise ValueError("registered rights period lacks its declared warmup and prior signal close")
    from .engine_checkpoint_codec import decode_engine_rights

    initial = decode_engine_rights(catalog.initial_checkpoint_json)
    state = initial.engine
    if (state.session != str(data.close.index[start-1].date()) or state.origin_session != state.session
            or state.cash != base.initial_cash or any(units for _, units in state.shares)
            or state.stops or state.pending or state.receivables or state.settlements
            or state.terminated or state.receivable_value or state.passive_submitted
            or initial.account.inventory.book.receipts or initial.account.authorizations):
        raise ValueError("registered historical rights root must be a clean candidate cash account")
    if initial.account.policy.elections:
        raise ValueError("registered study lacks a declared rights participation supplement")
    if not catalog.entries:
        raise ValueError("registered source verification requires an archived next or completed request")
    for entry in catalog.entries:
        supplied = load_day_archive(Path(requests_directory)/(entry.archive_sha256+".json"),
                                    expected_sha256=entry.archive_sha256)
        request, inputs = supplied.request, supplied.request.inputs
        if day_input_sha256(supplied) != entry.input_sha256:
            raise ValueError("registered catalog input identity differs from archived request")
        if (request.commands or request.conversion_risks or request.opening_stops or supplied.rights
                or request.account.policy != initial.account.policy):
            raise ValueError("registered study lacks authenticated rights commands, risk or mark adapters")
        if inputs.research != research or inputs.config != config or inputs.passive_without_risk_estimate:
            raise ValueError("registered rights settings differ from the frozen candidate")
        settings = fingerprint({"research": asdict(research), "config": asdict(config),
                                "lot_policy": asdict(request.lot_policy)})
        if settings != catalog.config.settings_sha256:
            raise ValueError("registered rights catalog settings identity differs")
        if inputs.origin_index != start-1 or not 0 <= inputs.signal_index < len(reference.close.index)-1:
            raise ValueError("registered rights request indexes differ from the period origin")
        session = str(reference.close.index[inputs.signal_index+1].date())
        if session != entry.session or not period.start <= session <= period.end:
            raise ValueError("registered rights day is outside its declared period")
        for field in fields(reference):
            if canonical(encode_value(getattr(inputs.data, field.name))) != canonical(encode_value(getattr(reference, field.name))):
                raise ValueError("registered rights source panels differ from frozen study originals")
        if canonical(encode_value(inputs.prior_liquidity)) != canonical(encode_value(prior_session_liquidity(reference.volume))):
            raise ValueError("registered rights prior liquidity differs from the frozen source")
    if load_protocol(binding.protocol_directory) != protocol or capture_execution_identity(source) != execution:
        raise ValueError("registered rights protocol or execution changed during authentication")
    load_frozen_odd_lot_study(study)
    with ReadOnlyExperimentRegistry(binding.registry_path) as registry:
        if registry.get_protocol(protocol.protocol_id) != protocol:
            raise ValueError("registered rights registry changed during authentication")
    return RegisteredRightsAssessment(protocol.protocol_id, candidate.candidate_id, candidate.study_id,
                                      period.name, period.purpose, len(catalog.entries))
