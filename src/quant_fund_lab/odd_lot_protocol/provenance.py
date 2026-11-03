"""Capture tracked changes, untracked source bytes and the actual runtime."""
from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

from .. import __version__
from ..twse_quality.types import fingerprint
from .types import ExecutionIdentity, canonical_json


def capture_execution_identity(directory: str | Path) -> ExecutionIdentity:
    """Bind engine, tests, verification and dependency files, including untracked files.

    Artifact/report output and progress documentation are excluded so recording a
    result cannot change the code identity of that same execution.
    """
    root = Path(directory).resolve()
    paths = ["src/quant_fund_lab", "tests", "scripts", "requirements", "pyproject.toml"]
    revision = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    diff = subprocess.check_output([
        "git", "-C", str(root), "diff", "HEAD", "--binary", "--", *paths,
        ":(glob,exclude)**/*.md", ":(glob,exclude)**/*.rst",
    ])
    files = {}
    for name in paths:
        location = root / name
        candidates = [location] if location.is_file() else location.rglob("*")
        for path in sorted(candidates):
            if path.suffix not in {".py", ".sh", ".toml", ".txt", ".json", ".csv"}:
                continue
            if path.is_symlink():
                raise ValueError("protocol source inventory cannot follow symlinks")
            if path.is_file():
                files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if "pyproject.toml" not in files:
        raise ValueError("execution identity requires the project source root")
    environment = {"python": sys.version, "implementation": platform.python_implementation(),
                   "platform": platform.platform(), "machine": platform.machine(),
                   "package_version": __version__, "dependencies": {name: version(name) for name in (
                       "numpy", "pandas", "scipy", "exchange-calendars", "pyarrow", "streamlit",
                   )}}
    return ExecutionIdentity(revision, hashlib.sha256(diff).hexdigest(), fingerprint(files),
                             canonical_json(environment))
