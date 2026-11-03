"""Content-addressed local daily request publication and checksum-pinned loading."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .day_request_codec import decode_day_request, encode_day_request
from .durable_day_audit import verify_durable_days
from .durable_day_workflow import DurableRightsDay, commit_rights_day
from .engine_ledger_types import payload_digest, sha256


@dataclass(frozen=True)
class DayRequestArchive:
    path: Path
    sha256: str


def _regular(path):
    if path.is_symlink() or not path.is_file() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("daily request archive must be a regular file outside symlink paths")


def load_day_archive(path: str | Path, *, expected_sha256: str) -> DurableRightsDay:
    """Require an externally retained checksum; an archive cannot attest itself.

    Local integrity does not certify issuer truth, original publication time or
    prior protocol registration. Retain this checksum in the reviewed catalog.
    """
    sha256(expected_sha256)
    target = Path(path).absolute()
    _regular(target)
    payload = target.read_text(encoding="utf-8")
    if payload_digest(payload) != expected_sha256:
        raise ValueError("daily request bytes differ from the expected archived checksum")
    result = decode_day_request(payload)
    _regular(target)
    if target.read_text(encoding="utf-8") != payload:
        raise ValueError("daily request archive changed during loading")
    return result


def archive_day_request(directory: str | Path, day: DurableRightsDay) -> DayRequestArchive:
    """Publish a complete canonical file once, preserving an existing archive.

    A temporary sibling is flushed before exclusive link publication. Failed
    writes never expose a partial final file or replace an existing path.
    """
    payload = encode_day_request(day)
    # Validate full reconstruction before exposing the file to other readers.
    decode_day_request(payload)
    identity = payload_digest(payload)
    root = Path(directory).absolute()
    if root.is_symlink() or any(parent.is_symlink() for parent in root.parents):
        raise ValueError("daily request archive directory cannot traverse symlinks")
    root.mkdir(parents=True, exist_ok=True)
    target = root/(identity+".json")
    if target.exists() or target.is_symlink():
        load_day_archive(target, expected_sha256=identity)
        return DayRequestArchive(target, identity)
    descriptor, temporary = tempfile.mkstemp(prefix=".request-", dir=root)
    staged = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(staged, target)
            directory_fd = os.open(root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except FileExistsError:
            load_day_archive(target, expected_sha256=identity)
    finally:
        staged.unlink(missing_ok=True)
    load_day_archive(target, expected_sha256=identity)
    return DayRequestArchive(target, identity)


def commit_archived_day(ledger, archive: DayRequestArchive, *, _fault=None):
    """Load an externally pinned request, then consume the public atomic workflow."""
    if not isinstance(archive, DayRequestArchive):
        raise TypeError("archived commit requires a typed path/checksum reference")
    day = load_day_archive(archive.path, expected_sha256=archive.sha256)

    def guard(phase):
        if _fault is not None:
            _fault(phase)
        load_day_archive(archive.path, expected_sha256=archive.sha256)

    return commit_rights_day(ledger, day, _fault=guard)


def verify_archived_days(ledger, archives: tuple[DayRequestArchive, ...]):
    """Independently check NAV/risk, then replay the externally pinned history.

    These are complementary checks: behavioral replay does not replace the
    independent equations, and neither authenticates external issuer truth.
    """
    if type(archives) is not tuple or any(not isinstance(row, DayRequestArchive) for row in archives):
        raise TypeError("archive replay requires an immutable typed reference catalog")
    days = tuple(load_day_archive(row.path, expected_sha256=row.sha256) for row in archives)
    from .persisted_nav_audit import verify_persisted_nav
    from .persisted_risk_audit import verify_persisted_risk

    verify_persisted_nav(ledger, days)
    verify_persisted_risk(ledger, days)
    result = verify_durable_days(ledger, days)
    for row in archives:
        load_day_archive(row.path, expected_sha256=row.sha256)
    return result
