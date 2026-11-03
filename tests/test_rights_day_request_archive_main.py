"""Original portable daily requests replay SQL after Python inputs are discarded."""
import json
from dataclasses import replace
from decimal import Decimal

import pandas as pd
import pytest
from rights_durable_day_fixtures import initial_day, next_day

from quant_fund_lab.odd_lot_rights.close_commands import RightsCloseCommand
from quant_fund_lab.odd_lot_rights.codec import canonical
from quant_fund_lab.odd_lot_rights.day_request_archive import (
    archive_day_request,
    commit_archived_day,
    load_day_archive,
    verify_archived_days,
)
from quant_fund_lab.odd_lot_rights.day_request_codec import decode_day_request, encode_day_request
from quant_fund_lab.odd_lot_rights.durable_day_workflow import day_input_sha256
from quant_fund_lab.odd_lot_rights.engine_ledger import RightsEngineLedger
from quant_fund_lab.odd_lot_rights.engine_ledger_types import payload_digest
from quant_fund_lab.odd_lot_rights.request_values_codec import decode_value, encode_value
from quant_fund_lab.odd_lot_rights.settlement import FractionalCashTerms


def test_seven_day_archive_loading_sql_restart_and_readonly_full_replay(tmp_path, monkeypatch):
    context, initial, config, day = initial_day(monkeypatch)
    path = tmp_path/"ledger.sqlite"
    ledger = RightsEngineLedger(path, config=config, initial=initial)
    archives = []
    for index in range(29, 36):
        if index > 29:
            day = next_day(context, ledger.verify()[0], index)
        archived = archive_day_request(tmp_path/"requests", day)
        before = archived.path.read_bytes()
        assert archive_day_request(tmp_path/"requests", day) == archived
        loaded = load_day_archive(archived.path, expected_sha256=archived.sha256)
        assert day_input_sha256(loaded) == day_input_sha256(day)
        assert encode_day_request(loaded) == encode_day_request(day)
        del loaded, day
        result = commit_archived_day(ledger, archived)
        assert result.nav.nav == 1050
        assert archived.path.read_bytes() == before
        archives.append(archived)
        ledger.close()
        ledger = RightsEngineLedger(path, config=config)
    assert ledger.verify()[0].engine.cash == 550.
    assert verify_archived_days(ledger, tuple(archives)).sessions_checked == 7
    ledger.close()
    before = path.read_bytes()
    readonly = RightsEngineLedger(path, config=config, read_only=True)
    assert verify_archived_days(readonly, tuple(archives)).sessions_checked == 7
    readonly.close()
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", ["version", "extra", "unknown_type", "missing_field", "duplicate_key"])
def test_portable_request_rejects_schema_or_type_changes(monkeypatch, change):
    _, _, _, day = initial_day(monkeypatch)
    encoded = encode_day_request(day)
    payload = json.loads(encoded)
    if change == "version":
        payload["schema_version"] = True
    elif change == "extra":
        payload["extra"] = 1
    elif change == "unknown_type":
        payload["inputs"]["research"][1] = "ArbitraryPythonImport"
    elif change == "missing_field":
        del payload["inputs"]["config"][2]["cash_annual_yield"]
    else:
        encoded = encoded.replace('"schema_version":1', '"schema_version":1,"schema_version":1', 1)
    with pytest.raises((ValueError, TypeError)):
        decode_day_request(encoded if change == "duplicate_key" else canonical(payload))


def test_valid_rewritten_request_still_requires_original_external_checksum(tmp_path, monkeypatch):
    _, _, _, day = initial_day(monkeypatch)
    archived = archive_day_request(tmp_path, day)
    changed = replace(day, valuation_at=day.valuation_at[:10]+"T16:11:00+08:00")
    payload = encode_day_request(changed)
    assert decode_day_request(payload).valuation_at == changed.valuation_at
    archived.path.write_text(payload)
    with pytest.raises(ValueError, match="expected archived checksum"):
        load_day_archive(archived.path, expected_sha256=archived.sha256)
    assert payload_digest(payload) != archived.sha256


def test_archive_symlink_and_publication_overwrite_are_refused(tmp_path, monkeypatch):
    _, _, _, day = initial_day(monkeypatch)
    archived = archive_day_request(tmp_path/"real", day)
    linked = tmp_path/"link"
    linked.symlink_to(archived.path)
    with pytest.raises(ValueError, match="symlink"):
        load_day_archive(linked, expected_sha256=archived.sha256)
    root = tmp_path/"linked-dir"
    root.symlink_to(archived.path.parent)
    with pytest.raises(ValueError, match="symlink"):
        archive_day_request(root, day)
    archived.path.write_text("corrupt")
    with pytest.raises(ValueError, match="expected archived checksum"):
        archive_day_request(tmp_path/"real", day)
    assert archived.path.read_text() == "corrupt"


@pytest.mark.parametrize("phase", ["checkpoint", "before_commit"])
def test_changed_archive_during_commit_rolls_back_combined_day(tmp_path, monkeypatch, phase):
    _, initial, config, day = initial_day(monkeypatch)
    archived = archive_day_request(tmp_path/"requests", day)
    ledger = RightsEngineLedger(tmp_path/"race.sqlite", config=config, initial=initial)
    baseline = ledger.verify()

    def mutate(where):
        if where == phase:
            archived.path.write_text("changed")

    with pytest.raises(ValueError, match="expected archived checksum"):
        commit_archived_day(ledger, archived, _fault=mutate)
    assert ledger.verify() == baseline
    ledger.close()


def test_optional_fractional_dates_and_currency_frames_survive_portable_request(monkeypatch):
    _, _, _, day = initial_day(monkeypatch)
    data = day.request.inputs.data
    settlement = pd.DataFrame(pd.NaT, index=data.close.index, columns=data.close.columns)
    settlement.iloc[30, 0] = data.close.index[33]
    prices = data.close*float("nan")
    prices.iloc[33, 0] = 100.
    codes = pd.DataFrame("TWD", index=data.close.index, columns=data.close.columns)
    changed = replace(data, cash_in_lieu_settlement_dates=settlement, cash_in_lieu_prices=prices,
                      currency_codes=codes)
    source = replace(day, request=replace(day.request, inputs=replace(day.request.inputs, data=changed)))
    loaded = decode_day_request(encode_day_request(source))
    assert day_input_sha256(source) == day_input_sha256(loaded)
    pd.testing.assert_frame_equal(changed.cash_in_lieu_settlement_dates,
                                   loaded.request.inputs.data.cash_in_lieu_settlement_dates)
    pd.testing.assert_frame_equal(changed.currency_codes, loaded.request.inputs.data.currency_codes)


def test_known_unused_command_variants_preserve_exact_types_and_decimal_values(monkeypatch):
    context, _, _, day = initial_day(monkeypatch)
    payment = context["authorization"].requests[0].terms
    stamp = day.request.close_at[:10]+"T16:01:00+08:00"
    terms = FractionalCashTerms(payment.right_key, Decimal("0.5"), Decimal("0.123456789012345678"),
                                stamp[:10], payment.available_at, payment.evidence_sha256)
    commands = (
        RightsCloseCommand("revise", stamp, "revise", context["event"], None),
        RightsCloseCommand("expire", stamp, "expire", payment, None),
        RightsCloseCommand("fraction", stamp, "fraction", terms, None))
    # Serialization does not execute or claim that these operations are payable
    # on this fixture day; their transition legality is checked by the workflow.
    for command in commands:
        encoded = encode_value(command)
        loaded = decode_value(encoded)
        assert loaded == command and type(loaded.terms) is type(command.terms)
    assert encode_value(decode_value(encode_value(context["mapping"]))) == encode_value(context["mapping"])


def test_noncanonical_or_unknown_frame_dtype_cannot_be_silently_cast(monkeypatch):
    _, _, _, day = initial_day(monkeypatch)
    payload = json.loads(encode_day_request(day))
    payload["data"]["volume"][1]["dtypes"][0] = "complex128"
    with pytest.raises(ValueError, match="unsupported portable"):
        decode_day_request(canonical(payload))
