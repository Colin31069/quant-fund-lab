"""Explicit, fail-closed choices for the local virtual paper ledger UI."""

from __future__ import annotations

from pathlib import Path


def plan_persistent_paper_run(
    ledger_path: str | Path,
    mode: str,
    *,
    confirmed_rebuild: bool = False,
) -> bool:
    """Return the replay reset flag, never deleting or creating files here.

    'continue' must find an existing SQLite file. 'rebuild' may replace one
    only after a separate explicit confirmation. This guard is pure so the
    UI can reject destructive work before downloading or simulating data.
    """

    path = Path(ledger_path)
    if path.exists() and not path.is_file():
        raise ValueError(f"paper ledger path is not a regular file: {path}")
    if mode == "continue":
        if not path.is_file():
            raise FileNotFoundError(
                f"no existing paper ledger at {path}; choose rebuild to create one"
            )
        return False
    if mode == "rebuild":
        if path.exists() and not confirmed_rebuild:
            raise ValueError(
                "rebuilding an existing paper ledger requires explicit confirmation "
                "and a backup of the SQLite ledger and snapshot directory"
            )
        return True
    raise ValueError("paper ledger mode must be 'continue' or 'rebuild'")
