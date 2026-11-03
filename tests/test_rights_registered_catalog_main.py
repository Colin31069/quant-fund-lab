"""Actual registry/protocol/raw study authenticity gates catalog SQL admission."""
from dataclasses import replace
from decimal import Decimal

import pytest
from rights_registered_catalog_fixtures import registered_catalog

from quant_fund_lab.odd_lot_paper.types import StopState
from quant_fund_lab.odd_lot_rights.close_commands import RightsCloseCommand
from quant_fund_lab.odd_lot_rights.conversion_risk import ReceiptRiskTransfer
from quant_fund_lab.odd_lot_rights.day_request_archive import archive_day_request
from quant_fund_lab.odd_lot_rights.durable_day_workflow import day_input_sha256
from quant_fund_lab.odd_lot_rights.engine_ledger import RightsEngineLedger
from quant_fund_lab.odd_lot_rights.registered_catalog_workflow import (
    commit_registered_catalog_day,
    verify_registered_catalog,
)
from quant_fund_lab.odd_lot_rights.registered_source import authenticate_registered_catalog
from quant_fund_lab.odd_lot_rights.types import EntitlementEvent, EntitlementLeg
from quant_fund_lab.odd_lot_rights.valuation import RightsMark


def test_registered_historical_day_verifies_native_sources_commits_and_noop_is_readonly(tmp_path, monkeypatch):
    binding, catalog, initial, _, _ = registered_catalog(tmp_path, monkeypatch)
    before_registry = binding.registry_path.read_bytes()
    assessment = authenticate_registered_catalog(binding, catalog, tmp_path/"requests")
    assert assessment.archives_checked == 1 and assessment.purpose != "forward_observation"
    ledger = RightsEngineLedger(tmp_path/"account.sqlite", config=catalog.config, initial=initial)
    result = commit_registered_catalog_day(ledger, catalog, tmp_path/"requests", binding)
    assert result is not None
    baseline = ledger.verify()
    assert commit_registered_catalog_day(ledger, catalog, tmp_path/"requests", binding) is None
    assert verify_registered_catalog(ledger, catalog, tmp_path/"requests", binding)[1][0] == baseline[0]
    assert ledger.verify() == baseline
    ledger.close()
    assert binding.registry_path.read_bytes() == before_registry


@pytest.mark.parametrize("change", ["registry", "candidate", "period", "execution", "protocol", "calendar", "raw"])
def test_invalid_registered_binding_is_rejected_without_account_creation(tmp_path, monkeypatch, change):
    binding, catalog, _, _, _ = registered_catalog(tmp_path, monkeypatch)
    if change == "registry":
        binding = replace(binding, registry_path=tmp_path/"missing.sqlite")
    elif change in {"candidate", "period"}:
        binding = replace(binding, **{change+"_id" if change == "candidate" else change: "f"*64})
    elif change in {"execution", "protocol", "calendar"}:
        catalog = replace(catalog, config=replace(catalog.config, **{change+"_sha256": "f"*64}))
    else:
        source = next((binding.studies_directory/next(binding.studies_directory.iterdir()).name/"sources/prices").glob("*.json"))
        source.write_bytes(source.read_bytes()+b" ")
    with pytest.raises(ValueError):
        authenticate_registered_catalog(binding, catalog, tmp_path/"requests")
    assert not (tmp_path/"account.sqlite").exists() and not (tmp_path/"missing.sqlite").exists()


@pytest.mark.parametrize("change", ["volume", "liquidity", "research"])
def test_other_self_consistent_archive_cannot_replace_registered_source_or_settings(tmp_path, monkeypatch, change):
    binding, catalog, _, day, _ = registered_catalog(tmp_path, monkeypatch)
    inputs = day.request.inputs
    if change == "volume":
        frame = inputs.data.volume.copy()
        frame.iloc[0, 0] += 1
        inputs = replace(inputs, data=replace(inputs.data, volume=frame))
    elif change == "liquidity":
        frame = inputs.prior_liquidity.copy()
        frame.iloc[1, 0] += 1
        inputs = replace(inputs, prior_liquidity=frame)
    else:
        inputs = replace(inputs, research=replace(inputs.research, risk_budget=999.))
    changed = replace(day, request=replace(day.request, inputs=inputs))
    archive = archive_day_request(tmp_path/"requests", changed)
    entry = replace(catalog.entries[0], archive_sha256=archive.sha256, input_sha256=day_input_sha256(changed))
    catalog = replace(catalog, entries=(entry,))
    with pytest.raises(ValueError):
        authenticate_registered_catalog(binding, catalog, tmp_path/"requests")


def test_raw_source_mutated_during_sql_admission_rolls_back_whole_day(tmp_path, monkeypatch):
    binding, catalog, initial, _, _ = registered_catalog(tmp_path, monkeypatch)
    ledger = RightsEngineLedger(tmp_path/"race.sqlite", config=catalog.config, initial=initial)
    baseline = ledger.verify()
    source = next((next(binding.studies_directory.iterdir())/"sources/prices").glob("*.json"))

    def mutate(phase):
        if phase == "before_commit":
            source.write_bytes(source.read_bytes()+b" ")

    with pytest.raises(ValueError):
        commit_registered_catalog_day(ledger, catalog, tmp_path/"requests", binding, _fault=mutate)
    assert ledger.verify() == baseline
    ledger.close()


@pytest.mark.parametrize("change", ["grant", "risk", "mark"])
def test_unverified_rights_commands_or_marks_cannot_hide_inside_registered_price_study(tmp_path, monkeypatch, change):
    binding, catalog, _, day, _ = registered_catalog(tmp_path, monkeypatch)
    stamp = day.valuation_at
    if change == "grant":
        terms = EntitlementEvent("a"*64, day.request.inputs.data.symbols[0], stamp[:10],
            stamp[:10]+"T08:00:00+08:00", ("b"*64,),
            (EntitlementLeg("unverified", "unverified-class", "subscription", Decimal("0.1")),))
        command = RightsCloseCommand("unverified-grant", stamp, "grant", terms, 1)
        changed = replace(day, request=replace(day.request, commands=(command,)))
    elif change == "risk":
        transfer = ReceiptRiskTransfer("fake-convert", StopState("fake.TW", 95., 100., .05),
                                       None, "carry_receipt_exit", False)
        changed = replace(day, request=replace(day.request, conversion_risks=(transfer,)))
    else:
        mark = RightsMark("unverified-right", "pending", Decimal(1), stamp[:10], stamp, ("b"*64,))
        changed = replace(day, rights=(mark,))
    archive = archive_day_request(tmp_path/"requests", changed)
    catalog = replace(catalog, entries=(replace(catalog.entries[0], archive_sha256=archive.sha256,
                                                input_sha256=day_input_sha256(changed)),))
    with pytest.raises(ValueError, match="lacks authenticated rights"):
        authenticate_registered_catalog(binding, catalog, tmp_path/"requests")


def test_historical_registered_entry_cannot_activate_an_unseen_forward_protocol(tmp_path, monkeypatch):
    from quant_fund_lab.odd_lot_protocol.registry import ExperimentRegistry
    from quant_fund_lab.odd_lot_protocol.storage import freeze_protocol, load_protocol

    binding, catalog, _, _, _ = registered_catalog(tmp_path, monkeypatch)
    original = load_protocol(binding.protocol_directory)
    period = replace(original.periods[0], start="2027-01-04", end="2027-01-29",
                     purpose="forward_observation", data_access="unseen")
    prospective = replace(original, periods=(period,))
    frozen = freeze_protocol(prospective, binding.protocol_directory.parent)
    with ExperimentRegistry(binding.registry_path) as registry:
        registry.register_protocol(prospective)
    binding = replace(binding, protocol_directory=frozen)
    catalog = replace(catalog, config=replace(catalog.config, protocol_sha256=prospective.protocol_id))
    with pytest.raises(ValueError, match="cannot activate forward"):
        authenticate_registered_catalog(binding, catalog, tmp_path/"requests")
