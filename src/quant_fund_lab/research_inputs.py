from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .cash_in_lieu_data import (
    CashInLieuSettlementManifest,
    load_cash_in_lieu_settlement_dataset,
)
from .data import MarketData
from .fx import attach_fx_rates
from .identity_market_data import stitch_market_data_by_identity
from .security_master_events import (
    SecurityLifecycleManifest,
    load_security_lifecycle_dataset,
)
from .snapshot import SnapshotManifest, load_market_data_snapshot


@dataclass(frozen=True)
class VerifiedResearchInputs:
    data: MarketData
    assets: pd.DataFrame
    market_snapshot: SnapshotManifest
    lifecycle_snapshot: SecurityLifecycleManifest
    data_provenance: dict[str, str]
    cash_in_lieu_snapshot: CashInLieuSettlementManifest | None = None


def _validated_market_snapshot(directory: str | Path) -> tuple[MarketData, SnapshotManifest]:
    root = Path(directory)
    data = load_market_data_snapshot(root)
    raw = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest = SnapshotManifest(
        dataset_id=str(raw["dataset_id"]),
        exchange=raw.get("exchange"),
        base_currency=raw.get("base_currency"),
        symbols=tuple(raw["symbols"]),
        start=str(raw["start"]),
        end=str(raw["end"]),
        files=dict(raw["files"]),
    )
    if tuple(data.symbols) != manifest.symbols:
        raise ValueError("market snapshot manifest symbols do not match loaded data")
    if str(pd.Timestamp(data.close.index.min()).date()) != manifest.start:
        raise ValueError("market snapshot manifest start does not match loaded data")
    if str(pd.Timestamp(data.close.index.max()).date()) != manifest.end:
        raise ValueError("market snapshot manifest end does not match loaded data")
    return data, manifest


def load_verified_identity_research_inputs(
    market_snapshot_directory: str | Path,
    lifecycle_snapshot_directory: str | Path,
    security_ids: list[str],
    *,
    cash_in_lieu_snapshot_directory: str | Path | None = None,
    base_currency: str | None = None,
    usd_twd: pd.Series | None = None,
    max_fx_staleness_days: int = 5,
) -> VerifiedResearchInputs:
    """Load, verify and compose point-in-time market and lifecycle research inputs."""

    market_data, market_manifest = _validated_market_snapshot(market_snapshot_directory)
    lifecycle, lifecycle_manifest = load_security_lifecycle_dataset(
        lifecycle_snapshot_directory
    )
    stitched = stitch_market_data_by_identity(market_data, lifecycle, security_ids)
    data = stitched.data
    cash_in_lieu_manifest: CashInLieuSettlementManifest | None = None
    if cash_in_lieu_snapshot_directory is not None:
        settlements, cash_in_lieu_manifest = load_cash_in_lieu_settlement_dataset(
            cash_in_lieu_snapshot_directory
        )
        data = settlements.apply_to_market_data(data, stitched.assets)

    requested_base = base_currency.upper() if base_currency is not None else None
    if requested_base is not None:
        has_matching_fx = (
            data.fx_to_base is not None
            and data.fx_age_days is not None
            and data.base_currency == requested_base
        )
        if not has_matching_fx:
            data = attach_fx_rates(
                data,
                requested_base,
                usd_twd=usd_twd,
                max_staleness_days=max_fx_staleness_days,
            )

    provenance = {
        "market_data_dataset_id": market_manifest.dataset_id,
        "security_lifecycle_dataset_id": lifecycle_manifest.dataset_id,
    }
    if cash_in_lieu_manifest is not None:
        provenance["cash_in_lieu_settlement_dataset_id"] = cash_in_lieu_manifest.dataset_id
    return VerifiedResearchInputs(
        data=data,
        assets=stitched.assets,
        market_snapshot=market_manifest,
        lifecycle_snapshot=lifecycle_manifest,
        data_provenance=provenance,
        cash_in_lieu_snapshot=cash_in_lieu_manifest,
    )
