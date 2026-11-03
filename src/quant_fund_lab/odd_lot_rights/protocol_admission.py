"""Bind catalog admission to an actual frozen, registered study protocol."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ..odd_lot_protocol.provenance import capture_execution_identity
from ..odd_lot_protocol.registry_read import ReadOnlyExperimentRegistry
from ..odd_lot_protocol.storage import load_protocol
from ..odd_lot_protocol.types import canonical_json
from ..odd_lot_research import OddLotResearchConfig, odd_lot_backtest_config
from ..odd_lot_study import _backtest_config
from .catalog_workflow import commit_catalog_day
from .codec import fingerprint
from .day_request_archive import load_day_archive
from .durable_day_workflow import day_input_sha256, day_settings_sha256
from .request_catalog import RightsRequestCatalog


@dataclass(frozen=True)
class RightsProtocolAdmission:
    protocol_id: str
    candidate_id: str
    period: str
    catalog_sha256: str
    execution_sha256: str
    requests_checked: int
    scope: str = "registered_frozen_protocol_and_local_catalog_binding_not_source_certification"


def verify_rights_protocol(catalog: RightsRequestCatalog, protocol_directory: str | Path,
                           registry_path: str | Path, *, candidate_id: str, period: str,
                           requests_directory: str | Path,
                           source_directory: str | Path) -> RightsProtocolAdmission:
    """Check the real protocol/registry and currently executing source identity.

    Historical replay is permitted for declared accessed periods. This does not
    turn historical data into unseen forward observations or admit actual issuer
    events. Source manifests, readiness and event facts remain separate gates.
    """
    if Path(source_directory).resolve() != Path(__file__).resolve().parents[3]:
        raise ValueError("rights admission source directory differs from executing package")
    protocol = load_protocol(protocol_directory)
    with ReadOnlyExperimentRegistry(registry_path) as registry:
        registered = registry.get_protocol(protocol.protocol_id)
    if registered != protocol or catalog.config.protocol_sha256 != protocol.protocol_id:
        raise ValueError("rights catalog differs from the actual registered frozen protocol")
    execution = capture_execution_identity(source_directory)
    if execution != protocol.execution or execution.identity != catalog.config.execution_sha256:
        raise ValueError("rights protocol execution differs from current code/runtime identity")
    if catalog.config.calendar_sha256 != fingerprint(list(protocol.calendar_revisions)):
        raise ValueError("rights catalog calendar differs from frozen protocol revisions")
    candidate = next((row for row in protocol.candidates if row.candidate_id == candidate_id), None)
    selected = next((row for row in protocol.periods if row.name == period), None)
    if candidate is None or selected is None:
        raise ValueError("rights admission requires a declared candidate and protocol period")
    if selected.purpose == "forward_observation":
        raise ValueError("rights catalog historical admission cannot activate a forward observation period")
    research = OddLotResearchConfig(**json.loads(candidate.research_json))
    engine_config = odd_lot_backtest_config(_backtest_config(json.loads(candidate.backtest_json)), research)
    for entry in catalog.entries:
        supplied = load_day_archive(Path(requests_directory)/(entry.archive_sha256+".json"),
                                    expected_sha256=entry.archive_sha256)
        inputs = supplied.request.inputs
        actual_session = str(inputs.data.close.index[inputs.signal_index+1].date())
        if (actual_session != entry.session or day_input_sha256(supplied) != entry.input_sha256
                or day_settings_sha256(supplied) != catalog.config.settings_sha256):
            raise ValueError("rights protocol catalog reference differs from its actual archived request")
        if (canonical_json(asdict(inputs.research)) != candidate.research_json
                or inputs.config != engine_config):
            raise ValueError("rights request assumptions differ from frozen candidate")
        if not selected.start <= entry.session <= selected.end:
            raise ValueError("rights catalog session lies outside its declared protocol period")
        if not set(inputs.data.symbols) <= set(protocol.symbols) | {protocol.benchmark}:
            raise ValueError("rights request contains securities outside the declared protocol universe")
    return RightsProtocolAdmission(protocol.protocol_id, candidate_id, period,
        catalog.catalog_sha256, execution.identity, len(catalog.entries))


def commit_protocol_catalog_day(ledger, catalog: RightsRequestCatalog, protocol_directory,
                                registry_path, *, candidate_id: str, period: str,
                                requests_directory, source_directory, _fault=None):
    """Revalidate actual protocol/registry/code at each SQL boundary, then commit.

    Uses the existing full-prefix catalog and archive checks. A positive result
    is a local protocol binding, not official data approval or real brokerage.
    """
    def verify():
        return verify_rights_protocol(catalog, protocol_directory, registry_path,
            candidate_id=candidate_id, period=period, requests_directory=requests_directory,
            source_directory=source_directory)
    baseline = verify()
    protocol_file = Path(protocol_directory)/"protocol.json"
    original = protocol_file.read_bytes()
    def guard(phase):
        if _fault is not None:
            _fault(phase)
        if protocol_file.read_bytes() != original or verify() != baseline:
            raise ValueError("registered protocol binding changed during rights SQL admission")
    return commit_catalog_day(ledger, catalog, requests_directory, _fault=guard)
