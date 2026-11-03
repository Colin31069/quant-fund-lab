"""Content-addressed original source bytes, separate from normalized market snapshots."""
from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from ..twse_odd_lot import TWSEInput
from .ledger import canonical, digest


@dataclass(frozen=True)
class SourceArchiveLink:
    archive_id: str
    manifest_sha256: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (any(not re.fullmatch(r"[a-f0-9]{64}", value)
                for value in (self.archive_id, self.manifest_sha256))
                or type(self.schema_version) is not int or self.schema_version != 1):
            raise ValueError("invalid source archive link")


def _validate_hashes(hashes: dict) -> None:
    if not isinstance(hashes, dict) or not hashes or "manifest.json" not in hashes:
        raise ValueError("source archive requires the original manifest and inventory")
    for name, value in hashes.items():
        path = PurePosixPath(name)
        if (not path.parts or not name or path.is_absolute() or path.as_posix() != name or ".." in path.parts
                or "\\" in name or not re.fullmatch(r"[a-f0-9]{64}", value)):
            raise ValueError("unsafe source archive path or hash")
        if any(parent.as_posix() in hashes for parent in path.parents if parent.as_posix() != "."):
            raise ValueError("source archive file/directory conflict")


def verify_source_archive(root: str | Path, link: SourceArchiveLink) -> Path:
    """Read only; verify exact directory inventory and every original byte hash."""
    root = Path(root)
    target = root / link.archive_id
    if root.is_symlink() or target.is_symlink() or not target.is_dir():
        raise ValueError("source archive is absent or symlinked")
    manifest = target / "archive.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("source archive manifest is absent or symlinked")
    raw = manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != link.manifest_sha256:
        raise ValueError("source archive manifest changed")
    value = json.loads(raw)
    if (set(value) != {"schema_version", "source_hashes"} or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or canonical(value).encode() != raw or digest(canonical(value)) != link.archive_id):
        raise ValueError("source archive identity differs")
    hashes = value["source_hashes"]
    _validate_hashes(hashes)
    source = target / "sources"
    expected = {"archive.json", "sources"}
    for name in hashes:
        path = PurePosixPath("sources") / name
        expected.add(path.as_posix())
        expected.update(parent.as_posix() for parent in path.parents if parent.as_posix() != ".")
    actual = set()
    for path in target.rglob("*"):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError("source archive contains a symlink or special file")
        actual.add(path.relative_to(target).as_posix())
    if actual != expected:
        raise ValueError("source archive file inventory differs")
    for name, expected_hash in hashes.items():
        if not (source / name).is_file() or hashlib.sha256((source / name).read_bytes()).hexdigest() != expected_hash:
            raise ValueError("source archive payload changed: " + name)
    return source


def publish_source_archive(inputs: TWSEInput, root: str | Path) -> SourceArchiveLink:
    """Publish originals without overwrite; a SQL rollback may leave an orphan archive."""
    hashes = dict(inputs.source_hashes)
    _validate_hashes(hashes)
    if set(inputs.source_files) != set(hashes):
        raise ValueError("source archive inventory differs from input files")
    manifest = canonical({"schema_version":1, "source_hashes":hashes})
    link = SourceArchiveLink(digest(manifest), hashlib.sha256(manifest.encode()).hexdigest())
    root = Path(root)
    if root.is_symlink():
        raise ValueError("source archive root cannot be symlinked")
    root.mkdir(parents=True, exist_ok=True)
    target = root / link.archive_id
    with tempfile.TemporaryDirectory(prefix=".source-archive-", dir=root) as temporary:
        staging = Path(temporary) / "payload"
        staging.mkdir()
        (staging / "archive.json").write_text(manifest, encoding="utf-8")
        for name, expected_hash in sorted(hashes.items()):
            original = inputs.source_files[name]
            if original.is_symlink() or not original.is_file():
                raise ValueError("source archive input must be a regular file: " + name)
            raw = original.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected_hash:
                raise ValueError("source archive input integrity failure: " + name)
            path = staging / "sources" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        # Recheck originals after copying; publication never certifies changed bytes.
        if inputs.source_hashes != hashes or any(
                path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != hashes[name]
                for name, path in inputs.source_files.items()):
            raise ValueError("source archive input changed during publication")
        if target.exists():
            verify_source_archive(root, link)
        else:
            try:
                os.rename(staging, target)
            except OSError as exc:
                if exc.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                    raise
            verify_source_archive(root, link)
    return link


def source_archive_record(link: SourceArchiveLink) -> dict:
    return asdict(link)
