"""Admit catalog-bound archived days and verify the actual completed prefix."""
from dataclasses import asdict
from pathlib import Path

from .codec import canonical
from .day_request_archive import (
    DayRequestArchive,
    commit_archived_day,
    load_day_archive,
    verify_archived_days,
)
from .durable_day_workflow import day_input_sha256, day_settings_sha256
from .engine_checkpoint_codec import encode_engine_rights
from .engine_ledger_types import payload_digest
from .request_catalog import RightsRequestCatalog, decode_request_catalog, encode_request_catalog


def _references(catalog, directory):
    return tuple(DayRequestArchive(Path(directory)/(row.archive_sha256+".json"), row.archive_sha256)
                 for row in catalog.entries)


def verify_catalog_ledger(ledger, catalog: RightsRequestCatalog, directory):
    """Verify all completed entries using the external fixed catalog and archives.

    A catalog can list the next pending day, but cannot omit completed history
    or rewrite its original source reference. Local freezing is not approval
    for real events or proof of protocol/market-source authenticity.
    """
    decode_request_catalog(encode_request_catalog(catalog))
    if (ledger.config_json != canonical(asdict(catalog.config))
            or ledger.initial_json != catalog.initial_checkpoint_json):
        raise ValueError("catalog root/configuration differs from this ledger")
    state, _ = ledger.verify()
    rows = ledger.connection.execute("SELECT session,state_json,input_digest FROM rights_checkpoints ORDER BY session").fetchall()
    if len(rows) > len(catalog.entries):
        raise ValueError("catalog omits completed ledger sessions")
    previous = catalog.initial_checkpoint_json
    refs = _references(catalog, directory)
    for index, ((session, checkpoint, inputs), entry) in enumerate(zip(rows, catalog.entries)):
        if (session != entry.session or inputs != entry.input_sha256
                or entry.predecessor_checkpoint_sha256 != payload_digest(previous)):
            raise ValueError("catalog entry differs from completed session source or predecessor")
        supplied = load_day_archive(refs[index].path, expected_sha256=entry.archive_sha256)
        if (day_input_sha256(supplied) != entry.input_sha256
                or day_settings_sha256(supplied) != catalog.config.settings_sha256):
            raise ValueError("catalog archive does not establish its listed source/settings")
        previous = checkpoint
    verify_archived_days(ledger, refs[:len(rows)])
    return state, len(rows)


def commit_catalog_day(ledger, catalog: RightsRequestCatalog, directory, *, _fault=None):
    """Consume exactly the next reference after full prefix verification."""
    state, completed = verify_catalog_ledger(ledger, catalog, directory)
    if completed >= len(catalog.entries):
        return None  # Full verification already ran; rerender/retry cannot send another day.
    if len(catalog.entries) != completed+1:
        raise ValueError("catalog admission requires exactly one next pending session")
    entry = catalog.entries[completed]
    if entry.predecessor_checkpoint_sha256 != payload_digest(encode_engine_rights(state)):
        raise ValueError("next catalog request has a stale predecessor checkpoint")
    reference = _references(catalog, directory)[completed]
    supplied = load_day_archive(reference.path, expected_sha256=reference.sha256)
    index = supplied.request.inputs.signal_index+1
    session = str(supplied.request.inputs.data.close.index[index].date())
    if session != entry.session or day_input_sha256(supplied) != entry.input_sha256:
        raise ValueError("next catalog request session/source differs from frozen reference")
    frozen = catalog.catalog_sha256

    def guard(phase):
        if _fault is not None:
            _fault(phase)
        if catalog.catalog_sha256 != frozen:
            raise ValueError("catalog changed during SQL admission")
        for row in _references(catalog, directory):
            load_day_archive(row.path, expected_sha256=row.sha256)

    return commit_archived_day(ledger, reference, _fault=guard)
