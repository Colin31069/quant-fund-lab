"""Explicit read-only inspection from an externally pinned request catalog."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .catalog_workflow import verify_catalog_ledger
from .day_request_archive import load_day_archive
from .durable_day_workflow import day_input_sha256, day_settings_sha256
from .engine_ledger import RightsEngineLedger
from .request_catalog_files import load_request_catalog


@dataclass(frozen=True)
class RightsCatalogInspection:
    session: str
    completed_sessions: int
    pending_catalog_sessions: int
    cash: str
    nav: str | None
    held_units: tuple[tuple[str, int], ...]
    recorded_authorizations: int
    catalog_sha256: str
    final_digest: str
    status: str = "local_integrity_checked_source_review_required"


def inspect_rights_catalog(account_path: str | Path, catalog_path: str | Path,
                           *, expected_catalog_sha256: str,
                           requests_directory: str | Path) -> RightsCatalogInspection:
    """Verify storage, independent NAV/risk and replay without creating a file.

    Caller must retain/authenticate expected_catalog_sha256 outside the mutable
    archive folder. A successful result is not historical source certification,
    protocol registration, actual-forward activation or authority to trade.
    """
    catalog = load_request_catalog(catalog_path, expected_sha256=expected_catalog_sha256)
    target = Path(account_path).absolute()
    if (target.is_symlink() or not target.is_file()
            or any(parent.is_symlink() for parent in target.parents)):
        raise ValueError("rights inspection requires an existing regular account outside symlink paths")
    ledger = RightsEngineLedger(target, config=catalog.config, read_only=True)
    try:
        state, completed = verify_catalog_ledger(ledger, catalog, requests_directory)
        # Prefix verification checks completed history. Inspection also checks
        # pending references before reporting that the supplied catalog is valid.
        for entry in catalog.entries[completed:]:
            request = load_day_archive(Path(requests_directory)/(entry.archive_sha256+".json"),
                                       expected_sha256=entry.archive_sha256)
            dates = request.request.inputs.data.close.index
            session = str(dates[request.request.inputs.signal_index+1].date())
            if (session != entry.session or day_input_sha256(request) != entry.input_sha256
                    or day_settings_sha256(request) != catalog.config.settings_sha256):
                raise ValueError("pending catalog archive session/source/settings differ")
        _, digest = ledger.verify()
        nav = None
        if completed:
            payload = ledger.connection.execute("SELECT events_json FROM rights_events WHERE session=?",
                                                (state.engine.session,)).fetchone()[0]
            nav = json.loads(payload)["rights_nav"][0]["nav"]
        result = RightsCatalogInspection(state.engine.session, completed, len(catalog.entries)-completed,
            str(state.account.inventory.cash), nav, tuple(sorted((symbol, units) for symbol, units
                in state.engine.shares if units)), len(state.account.authorizations),
            catalog.catalog_sha256, digest)
        # Reject a catalog replacement during potentially expensive full-prefix checks.
        load_request_catalog(catalog_path, expected_sha256=expected_catalog_sha256)
        return result
    finally:
        ledger.close()
