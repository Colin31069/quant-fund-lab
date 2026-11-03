"""Catalog revisions bind exact ledger roots, external checksums and SQL prefixes."""
import json
from dataclasses import replace

import pytest
from rights_durable_day_fixtures import initial_day, next_day

from quant_fund_lab.odd_lot_rights.catalog_workflow import commit_catalog_day, verify_catalog_ledger
from quant_fund_lab.odd_lot_rights.codec import canonical
from quant_fund_lab.odd_lot_rights.day_request_archive import archive_day_request
from quant_fund_lab.odd_lot_rights.day_request_codec import encode_day_request
from quant_fund_lab.odd_lot_rights.engine_checkpoint_codec import encode_engine_rights
from quant_fund_lab.odd_lot_rights.engine_ledger import RightsEngineLedger
from quant_fund_lab.odd_lot_rights.request_catalog import (
    RightsRequestCatalog,
    append_request_catalog,
    decode_request_catalog,
    encode_request_catalog,
    verify_catalog_extension,
)
from quant_fund_lab.odd_lot_rights.request_catalog_files import (
    freeze_request_catalog,
    load_request_catalog,
)


def setup(tmp_path, monkeypatch):
    context, initial, config, day = initial_day(monkeypatch)
    catalog = RightsRequestCatalog(config, encode_engine_rights(initial), (), None)
    ledger = RightsEngineLedger(tmp_path/"ledger.sqlite", config=config, initial=initial)
    return context, ledger, catalog, day


def test_seven_revisions_reopen_catalog_and_sql_verify_prior_history_and_noop(tmp_path, monkeypatch):
    context, ledger, catalog, day = setup(tmp_path, monkeypatch)
    root = freeze_request_catalog(tmp_path/"catalogs", catalog)
    preserved = {root.path: root.path.read_bytes()}
    for index in range(29, 36):
        state, _ = ledger.verify()
        if index > 29:
            day = next_day(context, state, index)
        archive = archive_day_request(tmp_path/"requests", day)
        child = append_request_catalog(catalog, archive, state)
        verify_catalog_extension(catalog, child)
        published = freeze_request_catalog(tmp_path/"catalogs", child, previous=catalog)
        loaded = load_request_catalog(published.path, expected_sha256=published.sha256)
        assert loaded == child
        done = commit_catalog_day(ledger, loaded, tmp_path/"requests")
        assert done.nav.nav == 1050
        before = ledger.verify()
        assert commit_catalog_day(ledger, loaded, tmp_path/"requests") is None
        assert ledger.verify() == before
        preserved[published.path] = published.path.read_bytes()
        catalog = loaded
    assert ledger.verify()[0].engine.cash == 550.
    assert verify_catalog_ledger(ledger, catalog, tmp_path/"requests")[1] == 7
    ledger.close()
    assert all(path.read_bytes() == payload for path, payload in preserved.items())


@pytest.mark.parametrize("change", ["root", "settings", "entry", "predecessor", "parent", "missing"])
def test_catalog_rewrite_cannot_enter_or_replace_existing_history(tmp_path, monkeypatch, change):
    _, ledger, catalog, day = setup(tmp_path, monkeypatch)
    archived = archive_day_request(tmp_path/"requests", day)
    child = append_request_catalog(catalog, archived, ledger.verify()[0])
    commit_catalog_day(ledger, child, tmp_path/"requests")
    original = ledger.verify()
    if change in {"root", "settings"}:
        field = "protocol_sha256" if change == "root" else "settings_sha256"
        bad = replace(child, config=replace(child.config, **{field: "f"*64}))
    elif change == "entry":
        bad = replace(child, entries=(replace(child.entries[0], input_sha256="f"*64),))
    elif change == "predecessor":
        bad = replace(child, entries=(replace(child.entries[0], predecessor_checkpoint_sha256="f"*64),))
    elif change == "parent":
        bad = replace(child, parent_catalog_sha256="f"*64)
        with pytest.raises(ValueError, match="revision changes"):
            verify_catalog_extension(catalog, bad)
        ledger.close()
        return
    else:
        bad = catalog
    with pytest.raises(ValueError):
        commit_catalog_day(ledger, bad, tmp_path/"requests")
    assert ledger.verify() == original
    ledger.close()


def test_other_valid_request_cannot_replace_a_frozen_archive_reference(tmp_path, monkeypatch):
    _, ledger, catalog, day = setup(tmp_path, monkeypatch)
    archived = archive_day_request(tmp_path/"requests", day)
    child = append_request_catalog(catalog, archived, ledger.verify()[0])
    changed = replace(day, valuation_at=day.valuation_at[:10]+"T16:11:00+08:00")
    archived.path.write_text(encode_day_request(changed))
    baseline = ledger.verify()
    with pytest.raises(ValueError, match="expected archived checksum"):
        commit_catalog_day(ledger, child, tmp_path/"requests")
    assert ledger.verify() == baseline
    ledger.close()


def test_catalog_publication_and_load_require_correct_parent_and_external_identity(tmp_path, monkeypatch):
    _, ledger, catalog, day = setup(tmp_path, monkeypatch)
    reference = freeze_request_catalog(tmp_path/"catalogs", catalog)
    child = append_request_catalog(catalog, archive_day_request(tmp_path/"requests", day), ledger.verify()[0])
    with pytest.raises(ValueError, match="requires its original parent"):
        freeze_request_catalog(tmp_path/"catalogs", child)
    payload = json.loads(encode_request_catalog(catalog))
    payload["config"]["protocol_sha256"] = "f"*64
    altered = canonical(payload)
    assert decode_request_catalog(altered).config.protocol_sha256 == "f"*64
    reference.path.write_text(altered)
    with pytest.raises(ValueError, match="external identity"):
        load_request_catalog(reference.path, expected_sha256=reference.sha256)
    ledger.close()


def test_completed_archive_mutation_during_next_day_commit_rolls_back(tmp_path, monkeypatch):
    context, ledger, catalog, day = setup(tmp_path, monkeypatch)
    first_file = archive_day_request(tmp_path/"requests", day)
    first = append_request_catalog(catalog, first_file, ledger.verify()[0])
    commit_catalog_day(ledger, first, tmp_path/"requests")
    state, _ = ledger.verify()
    second_day = next_day(context, state, 30)
    second_file = archive_day_request(tmp_path/"requests", second_day)
    second = append_request_catalog(first, second_file, state)
    before = ledger.verify()

    def mutate(phase):
        if phase == "before_commit":
            first_file.path.write_text("changed prior archive")

    with pytest.raises(ValueError, match="expected archived checksum"):
        commit_catalog_day(ledger, second, tmp_path/"requests", _fault=mutate)
    assert ledger.verify() == before
    ledger.close()


def test_wrong_predecessor_and_duplicate_session_cannot_append_catalog(tmp_path, monkeypatch):
    _, ledger, catalog, day = setup(tmp_path, monkeypatch)
    archived = archive_day_request(tmp_path/"requests", day)
    first = append_request_catalog(catalog, archived, ledger.verify()[0])
    with pytest.raises(ValueError, match="last listed session"):
        append_request_catalog(first, archived, ledger.verify()[0])
    ledger.close()
