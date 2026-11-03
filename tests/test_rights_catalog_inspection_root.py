"""User-facing inspection boundary verifies full history without account mutation."""
from decimal import Decimal

import pytest
from test_rights_request_catalog_main import setup

from quant_fund_lab.odd_lot_rights.catalog_inspection import inspect_rights_catalog
from quant_fund_lab.odd_lot_rights.catalog_workflow import commit_catalog_day
from quant_fund_lab.odd_lot_rights.day_request_archive import archive_day_request
from quant_fund_lab.odd_lot_rights.request_catalog import append_request_catalog
from quant_fund_lab.odd_lot_rights.request_catalog_files import freeze_request_catalog


def inventory(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}


@pytest.mark.parametrize("completed", [False, True])
def test_catalog_inspection_reads_pending_or_completed_day_and_preserves_all_bytes(tmp_path, monkeypatch, completed):
    _, ledger, catalog, day = setup(tmp_path, monkeypatch)
    archived = archive_day_request(tmp_path/"requests", day)
    child = append_request_catalog(catalog, archived, ledger.verify()[0])
    frozen = freeze_request_catalog(tmp_path/"catalogs", child, previous=catalog)
    if completed:
        commit_catalog_day(ledger, child, tmp_path/"requests")
    ledger.close()
    before = inventory(tmp_path)
    result = inspect_rights_catalog(tmp_path/"ledger.sqlite", frozen.path,
        expected_catalog_sha256=frozen.sha256, requests_directory=tmp_path/"requests")
    assert result.completed_sessions == int(completed)
    assert result.pending_catalog_sessions == int(not completed)
    assert result.nav == ("1050" if completed else None)
    assert Decimal(result.cash) == (50 if completed else 100)
    assert result.recorded_authorizations == int(completed)
    assert result.status == "local_integrity_checked_source_review_required"
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("change", ["missing_account", "checksum", "symlink", "archive", "pending_archive"])
def test_inspection_cannot_initialize_missing_account_or_accept_changed_external_catalog(tmp_path, monkeypatch, change):
    _, ledger, catalog, day = setup(tmp_path, monkeypatch)
    archived = archive_day_request(tmp_path/"requests", day)
    child = append_request_catalog(catalog, archived, ledger.verify()[0])
    frozen = freeze_request_catalog(tmp_path/"catalogs", child, previous=catalog)
    if change != "pending_archive":
        commit_catalog_day(ledger, child, tmp_path/"requests")
    ledger.close()
    account, digest = tmp_path/"ledger.sqlite", frozen.sha256
    if change == "missing_account":
        account = tmp_path/"missing.sqlite"
    elif change == "checksum":
        digest = "f"*64
    elif change == "symlink":
        link = tmp_path/"link.sqlite"
        link.symlink_to(account)
        account = link
    else:
        archived.path.write_text("{}")
    before = inventory(tmp_path)
    with pytest.raises(ValueError):
        inspect_rights_catalog(account, frozen.path, expected_catalog_sha256=digest,
                               requests_directory=tmp_path/"requests")
    assert inventory(tmp_path) == before
    assert not (tmp_path/"missing.sqlite").exists()
