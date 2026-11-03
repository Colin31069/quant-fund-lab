"""Immutable request catalog binds pinned archives to one exact ledger root."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from .codec import canonical
from .day_request_archive import DayRequestArchive, load_day_archive
from .durable_day_workflow import day_input_sha256, day_settings_sha256
from .engine_checkpoint import RightsEngineCheckpoint
from .engine_checkpoint_codec import decode_engine_rights, encode_engine_rights
from .engine_ledger_types import RightsLedgerConfig, payload_digest, sha256
from .types import day


@dataclass(frozen=True)
class RequestCatalogEntry:
    session: str
    archive_sha256: str
    input_sha256: str
    predecessor_checkpoint_sha256: str

    def __post_init__(self) -> None:
        day(self.session)
        for value in (self.archive_sha256, self.input_sha256, self.predecessor_checkpoint_sha256):
            sha256(value)


@dataclass(frozen=True)
class RightsRequestCatalog:
    """A locally frozen catalog, not proof of external review or publication time.

    Every revision preserves all earlier entries and points to its parent ID.
    Initial state and all six ledger identities are bound by the catalog ID.
    The caller retains/authenticates that ID outside the mutable archive folder.
    """

    config: RightsLedgerConfig
    initial_checkpoint_json: str
    entries: tuple[RequestCatalogEntry, ...]
    parent_catalog_sha256: str | None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (not isinstance(self.config, RightsLedgerConfig) or type(self.schema_version) is not int
                or self.schema_version != 1):
            raise ValueError("request catalog requires a supported schema and typed ledger config")
        if (type(self.entries) is not tuple
                or any(not isinstance(row, RequestCatalogEntry) for row in self.entries)):
            raise TypeError("catalog entries require an immutable typed tuple")
        initial = decode_engine_rights(self.initial_checkpoint_json)
        if (payload_digest(self.initial_checkpoint_json) != self.config.initial_checkpoint_sha256
                or initial.account.policy.policy_sha256 != self.config.policy_sha256
                or initial.engine.session_offset != 0):
            raise ValueError("catalog initial state differs from pinned ledger identities")
        sessions = tuple(row.session for row in self.entries)
        if sessions != tuple(sorted(set(sessions))) or any(value <= initial.engine.session for value in sessions):
            raise ValueError("catalog sessions must be unique and ordered after the initial state")
        if len({row.archive_sha256 for row in self.entries}) != len(self.entries):
            raise ValueError("catalog cannot assign one archive to multiple sessions")
        if self.parent_catalog_sha256 is not None:
            sha256(self.parent_catalog_sha256)

    @property
    def catalog_sha256(self) -> str:
        return payload_digest(encode_request_catalog(self))


def encode_request_catalog(catalog: RightsRequestCatalog) -> str:
    return canonical(asdict(catalog))


def decode_request_catalog(payload: str) -> RightsRequestCatalog:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate request catalog JSON key")
            result[key] = value
        return result

    values = json.loads(payload, object_pairs_hook=unique)
    if not isinstance(values, dict) or set(values) != {
            "config", "initial_checkpoint_json", "entries", "parent_catalog_sha256", "schema_version"}:
        raise ValueError("request catalog schema fields differ")
    values["config"] = RightsLedgerConfig(**values["config"])
    values["entries"] = tuple(RequestCatalogEntry(**row) for row in values["entries"])
    result = RightsRequestCatalog(**values)
    if encode_request_catalog(result) != payload:
        raise ValueError("request catalog is not canonical")
    return result


def append_request_catalog(catalog: RightsRequestCatalog, archive: DayRequestArchive,
                            predecessor: RightsEngineCheckpoint) -> RightsRequestCatalog:
    """Append one explicitly supplied request; do not mutate old catalog bytes.

    Registration here means local content freezing. It does not establish that
    the source/alpha or rights terms were known before this historical session.
    SQL admission additionally verifies actual completed history and predecessor.
    """
    decode_request_catalog(encode_request_catalog(catalog))
    supplied = load_day_archive(archive.path, expected_sha256=archive.sha256)
    if day_settings_sha256(supplied) != catalog.config.settings_sha256:
        raise ValueError("catalog request settings differ from its frozen ledger configuration")
    from .durable_day_workflow import prepare_durable_day

    # Full preparation validates the predecessor runtime/account and all marks
    # before adding an executable reference to this catalog revision.
    result, _, _ = prepare_durable_day(predecessor, "0"*64, supplied)
    session = result.projection.checkpoint.session
    if catalog.entries:
        if predecessor.engine.session != catalog.entries[-1].session:
            raise ValueError("catalog append must follow its last listed session")
    elif encode_engine_rights(predecessor) != catalog.initial_checkpoint_json:
        raise ValueError("catalog first request must follow its pinned initial state")
    entry = RequestCatalogEntry(session, archive.sha256, day_input_sha256(supplied),
                                payload_digest(encode_engine_rights(predecessor)))
    return RightsRequestCatalog(catalog.config, catalog.initial_checkpoint_json,
        (*catalog.entries, entry), catalog.catalog_sha256)


def verify_catalog_extension(previous: RightsRequestCatalog, current: RightsRequestCatalog) -> None:
    if (current.parent_catalog_sha256 != previous.catalog_sha256
            or current.config != previous.config
            or current.initial_checkpoint_json != previous.initial_checkpoint_json
            or len(current.entries) != len(previous.entries)+1
            or current.entries[:-1] != previous.entries):
        raise ValueError("catalog revision changes its frozen root or completed reference prefix")
