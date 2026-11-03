"""Actual frozen protocol and readonly registry gate catalog-based SQL admission."""
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from protocol_fixtures import protocol as prototype
from rights_durable_day_fixtures import initial_day

from quant_fund_lab.odd_lot_protocol import (
    ExperimentRegistry,
    capture_execution_identity,
    freeze_protocol,
)
from quant_fund_lab.odd_lot_protocol.types import ProtocolCandidate, canonical_json
from quant_fund_lab.odd_lot_rights.codec import fingerprint
from quant_fund_lab.odd_lot_rights.day_request_archive import archive_day_request
from quant_fund_lab.odd_lot_rights.engine_checkpoint_codec import encode_engine_rights
from quant_fund_lab.odd_lot_rights.engine_ledger import RightsEngineLedger
from quant_fund_lab.odd_lot_rights.protocol_admission import (
    commit_protocol_catalog_day,
    verify_rights_protocol,
)
from quant_fund_lab.odd_lot_rights.request_catalog import (
    RightsRequestCatalog,
    append_request_catalog,
)

SOURCE = Path(__file__).resolve().parents[1]


def setup(tmp_path, monkeypatch, *, register=True, mismatch=None):
    _, initial, config, day = initial_day(monkeypatch)
    inputs = day.request.inputs
    research, base = asdict(inputs.research), asdict(inputs.config)
    if mismatch == "research":
        research["risk_budget"] += 1
    elif mismatch == "engine_config":
        base["initial_cash"] += 1
    candidate = ProtocolCandidate("1"*24, canonical_json(research), canonical_json(base))
    protocol = replace(prototype(), symbols=tuple(inputs.data.symbols), candidates=(candidate,),
                       execution=capture_execution_identity(SOURCE))
    if mismatch == "universe":
        protocol = replace(protocol, symbols=("2330.TW", "2317.TW"))
    elif mismatch == "dates":
        protocol = replace(protocol, periods=(replace(protocol.periods[0], start="2023-01-01", end="2023-12-31"),))
    elif mismatch == "forward":
        protocol = replace(protocol, periods=(replace(protocol.periods[0], start="2027-01-01", end="2027-12-31",
            purpose="forward_observation", data_access="unseen"),))
    frozen = freeze_protocol(protocol, tmp_path/"protocols")
    registry = tmp_path/"registry.sqlite"
    with ExperimentRegistry(registry) as store:
        if register:
            store.register_protocol(protocol)
    config = replace(config, protocol_sha256=protocol.protocol_id,
        execution_sha256=protocol.execution.identity, calendar_sha256=fingerprint(list(protocol.calendar_revisions)))
    ledger = RightsEngineLedger(tmp_path/"rights.sqlite", config=config, initial=initial)
    root = RightsRequestCatalog(config, encode_engine_rights(initial), (), None)
    archive = archive_day_request(tmp_path/"requests", day)
    catalog = append_request_catalog(root, archive, initial)
    return ledger, catalog, protocol, candidate, frozen, registry


def verify(catalog, candidate, frozen, registry, root):
    return verify_rights_protocol(catalog, frozen, registry, candidate_id=candidate.candidate_id,
        period="validation", requests_directory=root/"requests", source_directory=SOURCE)


def test_actual_protocol_registry_and_current_execution_admit_exact_catalog_day(tmp_path, monkeypatch):
    ledger, catalog, protocol, candidate, frozen, registry = setup(tmp_path, monkeypatch)
    before = {path: path.read_bytes() for path in (frozen/"protocol.json", registry)}
    binding = verify(catalog, candidate, frozen, registry, tmp_path)
    assert binding.protocol_id == protocol.protocol_id and binding.requests_checked == 1
    result = commit_protocol_catalog_day(ledger, catalog, frozen, registry,
        candidate_id=candidate.candidate_id, period="validation", requests_directory=tmp_path/"requests",
        source_directory=SOURCE)
    assert result.nav.nav == 1050 and ledger.verify()[0].engine.cash == 50
    assert commit_protocol_catalog_day(ledger, catalog, frozen, registry,
        candidate_id=candidate.candidate_id, period="validation", requests_directory=tmp_path/"requests",
        source_directory=SOURCE) is None
    assert before == {path: path.read_bytes() for path in before}
    ledger.close()


@pytest.mark.parametrize("change", ["protocol", "execution", "calendar", "candidate", "period", "registry_missing", "unregistered"])
def test_mismatched_or_unregistered_protocol_cannot_write_account(tmp_path, monkeypatch, change):
    ledger, catalog, _, candidate, frozen, registry = setup(tmp_path, monkeypatch, register=change != "unregistered")
    before = ledger.verify()
    kwargs = {"candidate_id": candidate.candidate_id, "period": "validation",
              "requests_directory": tmp_path/"requests", "source_directory": SOURCE}
    if change in {"protocol", "execution", "calendar"}:
        catalog = replace(catalog, config=replace(catalog.config, **{change+"_sha256": "f"*64}))
    elif change == "candidate":
        kwargs["candidate_id"] = "f"*64
    elif change == "period":
        kwargs["period"] = "undeclared"
    elif change == "registry_missing":
        registry = tmp_path/"missing.sqlite"
    with pytest.raises(ValueError):
        commit_protocol_catalog_day(ledger, catalog, frozen, registry, **kwargs)
    assert ledger.verify() == before
    assert not (tmp_path/"missing.sqlite").exists()
    ledger.close()


@pytest.mark.parametrize("phase", ["checkpoint", "before_commit"])
def test_protocol_envelope_replacement_during_transaction_rolls_back_day(tmp_path, monkeypatch, phase):
    ledger, catalog, _, candidate, frozen, registry = setup(tmp_path, monkeypatch)
    before = ledger.verify()
    def mutate(where):
        if where == phase:
            file = frozen/"protocol.json"
            envelope = json.loads(file.read_text())
            # Semantically valid protocol, different recording envelope bytes.
            envelope["recorded_at"] = "2026-10-28T00:00:00+00:00"
            file.write_text(canonical_json(envelope))
    with pytest.raises(ValueError, match="binding changed"):
        commit_protocol_catalog_day(ledger, catalog, frozen, registry,
            candidate_id=candidate.candidate_id, period="validation", requests_directory=tmp_path/"requests",
            source_directory=SOURCE, _fault=mutate)
    assert ledger.verify() == before and not ledger.verify()[0].account.authorizations
    ledger.close()


@pytest.mark.parametrize("mismatch", ["research", "engine_config", "universe", "dates", "forward"])
def test_genuine_registered_protocol_must_match_actual_settings_universe_and_period(tmp_path, monkeypatch, mismatch):
    ledger, catalog, _, candidate, frozen, registry = setup(tmp_path, monkeypatch, mismatch=mismatch)
    before = ledger.verify()
    with pytest.raises(ValueError):
        commit_protocol_catalog_day(ledger, catalog, frozen, registry,
            candidate_id=candidate.candidate_id, period="validation", requests_directory=tmp_path/"requests",
            source_directory=SOURCE)
    assert ledger.verify() == before
    ledger.close()
