"""Reconstructible selection CSVs retain original provider and raw-row identity."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .selection import price_selection_records
from .types import PriceSelection


def price_selection_csv(selection: PriceSelection) -> bytes:
    """Encode the same deterministic UTF-8 CSV for publication and verification."""
    return pd.DataFrame(price_selection_records(selection)).to_csv(index=False).encode("utf-8")


def verify_price_selection_report(directory: Path, selection: PriceSelection, manifest: dict) -> bool:
    """A rehashed report must still match its independently rebuilt source selection."""
    name = "price_selection.csv"
    if name not in manifest["files"]:
        return False
    try:
        return (directory / name).read_bytes() == price_selection_csv(selection)
    except (OSError, ValueError, TypeError, KeyError):
        return False
