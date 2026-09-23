from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd

from .data import MarketData

_REQUIRED_COLUMNS = [
    "security_id",
    "symbol",
    "exchange",
    "currency",
    "tradable_from",
    "tradable_until",
    "terminal_event_at",
    "terminal_return",
    "source",
]
_SCHEMA_VERSION = 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class SecurityMasterCoverage:
    requested_symbols: int
    covered_symbols: int
    missing_symbols: tuple[str, ...]
    bounded_symbols: int
    terminal_events: int


@dataclass(frozen=True)
class SecurityMasterManifest:
    schema_version: int
    dataset_id: str
    row_count: int
    symbols: tuple[str, ...]
    file_sha256: str


@dataclass(frozen=True)
class SecurityMaster:
    records: pd.DataFrame

    def __post_init__(self) -> None:
        missing = [column for column in _REQUIRED_COLUMNS if column not in self.records.columns]
        if missing:
            raise ValueError(f"security master missing columns: {missing}")
        frame = self.records[_REQUIRED_COLUMNS].copy()
        frame["security_id"] = frame["security_id"].astype(str).str.strip()
        frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
        frame["exchange"] = frame["exchange"].astype(str).str.upper().str.strip()
        frame["currency"] = frame["currency"].astype(str).str.upper().str.strip()
        frame["source"] = frame["source"].astype(str)
        for column in ("tradable_from", "tradable_until", "terminal_event_at"):
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
        frame["terminal_return"] = pd.to_numeric(frame["terminal_return"], errors="coerce")
        if frame["security_id"].eq("").any() or frame["symbol"].eq("").any():
            raise ValueError("security_id and symbol cannot be empty")
        if frame["exchange"].eq("").any() or frame["currency"].eq("").any():
            raise ValueError("exchange and currency cannot be empty")
        if frame["security_id"].duplicated().any():
            duplicated_ids = sorted(
                frame.loc[frame["security_id"].duplicated(keep=False), "security_id"].unique()
            )
            raise ValueError(f"security_id must be unique: {duplicated_ids}")
        if frame["symbol"].duplicated().any():
            duplicated = sorted(frame.loc[frame["symbol"].duplicated(keep=False), "symbol"].unique())
            raise ValueError(f"security master requires one active identity row per symbol: {duplicated}")
        if frame["tradable_from"].isna().any():
            raise ValueError("tradable_from is required for every security")
        bounded = frame["tradable_until"].notna()
        if bool((frame.loc[bounded, "tradable_until"] < frame.loc[bounded, "tradable_from"]).any()):
            raise ValueError("tradable_until cannot precede tradable_from")
        terminal = frame["terminal_event_at"].notna()
        terminal_return = frame["terminal_return"].notna()
        if bool((terminal & ~bounded).any()):
            raise ValueError("terminal_event_at requires tradable_until")
        if bool((terminal & ~terminal_return).any()):
            raise ValueError("terminal_event_at requires an explicit terminal_return")
        if bool((~terminal & terminal_return).any()):
            raise ValueError("terminal_return requires terminal_event_at")
        if bool((frame["terminal_return"].dropna() < -1.0).any()):
            raise ValueError("terminal_return cannot be below -100%")
        invalid_terminal_order = terminal & bounded & (
            frame["terminal_event_at"] <= frame["tradable_until"]
        )
        if bool(invalid_terminal_order.any()):
            raise ValueError("terminal_event_at must be after the last tradable date")
        object.__setattr__(
            self,
            "records",
            frame.sort_values(["symbol", "tradable_from"], kind="stable").reset_index(drop=True),
        )

    @property
    def symbols(self) -> list[str]:
        return self.records["symbol"].tolist()

    def coverage(self, symbols: list[str]) -> SecurityMasterCoverage:
        requested = list(dict.fromkeys(str(symbol).upper().strip() for symbol in symbols))
        covered = set(self.symbols).intersection(requested)
        rows = self.records[self.records["symbol"].isin(covered)]
        return SecurityMasterCoverage(
            requested_symbols=len(requested),
            covered_symbols=len(covered),
            missing_symbols=tuple(sorted(set(requested) - covered)),
            bounded_symbols=int(rows["tradable_until"].notna().sum()),
            terminal_events=int(rows["terminal_event_at"].notna().sum()),
        )

    def membership_panel(
        self,
        dates: pd.DatetimeIndex,
        symbols: list[str],
        require_complete: bool = True,
    ) -> pd.DataFrame:
        dates = pd.DatetimeIndex(dates)
        normalized_symbols = [str(symbol).upper().strip() for symbol in symbols]
        coverage = self.coverage(normalized_symbols)
        if require_complete and coverage.missing_symbols:
            raise ValueError(f"security master missing symbols: {list(coverage.missing_symbols)}")
        membership = pd.DataFrame(False, index=dates, columns=normalized_symbols, dtype=bool)
        indexed = self.records.set_index("symbol")
        for symbol in normalized_symbols:
            if symbol not in indexed.index:
                continue
            row = indexed.loc[symbol]
            active = dates >= pd.Timestamp(row["tradable_from"])
            if pd.notna(row["tradable_until"]):
                active &= dates <= pd.Timestamp(row["tradable_until"])
            membership[symbol] = active
        return membership

    def terminal_return_panel(
        self,
        dates: pd.DatetimeIndex,
        symbols: list[str],
        require_complete: bool = True,
    ) -> pd.DataFrame:
        dates = pd.DatetimeIndex(dates)
        normalized_symbols = [str(symbol).upper().strip() for symbol in symbols]
        coverage = self.coverage(normalized_symbols)
        if require_complete and coverage.missing_symbols:
            raise ValueError(f"security master missing symbols: {list(coverage.missing_symbols)}")
        panel = pd.DataFrame(float("nan"), index=dates, columns=normalized_symbols, dtype=float)
        indexed = self.records.set_index("symbol")
        for symbol in normalized_symbols:
            if symbol not in indexed.index:
                continue
            row = indexed.loc[symbol]
            if pd.isna(row["terminal_event_at"]):
                continue
            event_at = pd.Timestamp(row["terminal_event_at"])
            location = dates.searchsorted(event_at, side="left")
            if location < len(dates):
                panel.loc[dates[location], symbol] = float(row["terminal_return"])
        return panel

    def apply_to_market_data(
        self,
        data: MarketData,
        require_complete: bool = True,
    ) -> MarketData:
        membership = self.membership_panel(data.close.index, data.symbols, require_complete)
        terminal_returns = self.terminal_return_panel(
            data.close.index, data.symbols, require_complete
        )
        return replace(data, membership=membership, terminal_returns=terminal_returns)


def save_security_master(master: SecurityMaster, directory: str | Path) -> SecurityMasterManifest:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    data_path = root / "security_master.parquet"
    master.records.to_parquet(data_path, engine="pyarrow", compression="zstd", index=False)
    file_hash = _sha256(data_path)
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "row_count": len(master.records),
        "symbols": master.symbols,
        "file_sha256": file_hash,
    }
    dataset_id = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest = SecurityMasterManifest(
        schema_version=_SCHEMA_VERSION,
        dataset_id=dataset_id,
        row_count=len(master.records),
        symbols=tuple(master.symbols),
        file_sha256=file_hash,
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": manifest.schema_version,
                "dataset_id": manifest.dataset_id,
                "row_count": manifest.row_count,
                "symbols": list(manifest.symbols),
                "file_sha256": manifest.file_sha256,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return manifest


def load_security_master(directory: str | Path) -> tuple[SecurityMaster, SecurityMasterManifest]:
    root = Path(directory)
    manifest_raw = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if int(manifest_raw.get("schema_version", -1)) != _SCHEMA_VERSION:
        raise ValueError("unsupported security-master schema version")
    data_path = root / "security_master.parquet"
    observed_hash = _sha256(data_path)
    expected_hash = str(manifest_raw["file_sha256"])
    if observed_hash != expected_hash:
        raise ValueError("security-master file hash mismatch")
    payload = {
        "schema_version": int(manifest_raw["schema_version"]),
        "row_count": int(manifest_raw["row_count"]),
        "symbols": list(manifest_raw["symbols"]),
        "file_sha256": expected_hash,
    }
    dataset_id = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if dataset_id != manifest_raw["dataset_id"]:
        raise ValueError("security-master dataset ID mismatch")
    master = SecurityMaster(pd.read_parquet(data_path))
    manifest = SecurityMasterManifest(
        schema_version=_SCHEMA_VERSION,
        dataset_id=dataset_id,
        row_count=int(manifest_raw["row_count"]),
        symbols=tuple(manifest_raw["symbols"]),
        file_sha256=expected_hash,
    )
    if len(master.records) != manifest.row_count or tuple(master.symbols) != manifest.symbols:
        raise ValueError("security-master manifest content mismatch")
    return master, manifest
