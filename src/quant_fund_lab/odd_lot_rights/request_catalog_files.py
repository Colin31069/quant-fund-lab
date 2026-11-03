"""Exclusive revision publication and externally pinned request-catalog loading."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .day_request_archive import DayRequestArchive, _regular
from .engine_ledger_types import payload_digest, sha256
from .request_catalog import (
    RightsRequestCatalog,
    decode_request_catalog,
    encode_request_catalog,
    verify_catalog_extension,
)


def load_request_catalog(path: str | Path, *, expected_sha256: str) -> RightsRequestCatalog:
    """Verify external catalog identity before exposing any request reference."""
    sha256(expected_sha256)
    target = Path(path).absolute()
    _regular(target)
    payload = target.read_text(encoding="utf-8")
    if payload_digest(payload) != expected_sha256:
        raise ValueError("request catalog differs from expected external identity")
    result = decode_request_catalog(payload)
    _regular(target)
    if target.read_text(encoding="utf-8") != payload:
        raise ValueError("request catalog changed during loading")
    return result


def freeze_request_catalog(directory: str | Path, catalog: RightsRequestCatalog, *,
                            previous: RightsRequestCatalog | None = None) -> DayRequestArchive:
    """Publish a root or one-entry extension; retain every previous revision.

    The returned checksum must be retained in an authenticated review/registration
    channel. This local operation does not create that external attestation.
    """
    payload = encode_request_catalog(catalog)
    decode_request_catalog(payload)
    if previous is None:
        if catalog.entries or catalog.parent_catalog_sha256 is not None:
            raise ValueError("non-root catalog publication requires its original parent revision")
    else:
        verify_catalog_extension(previous, catalog)
    root = Path(directory).absolute()
    if root.is_symlink() or any(parent.is_symlink() for parent in root.parents):
        raise ValueError("catalog directory cannot traverse symlink paths")
    root.mkdir(parents=True, exist_ok=True)
    identity = payload_digest(payload)
    target = root/(identity+".json")
    if target.exists() or target.is_symlink():
        load_request_catalog(target, expected_sha256=identity)
        return DayRequestArchive(target, identity)
    descriptor, filename = tempfile.mkstemp(prefix=".catalog-", dir=root)
    staged = Path(filename)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(staged, target)
        except FileExistsError:
            load_request_catalog(target, expected_sha256=identity)
        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        staged.unlink(missing_ok=True)
    load_request_catalog(target, expected_sha256=identity)
    return DayRequestArchive(target, identity)
