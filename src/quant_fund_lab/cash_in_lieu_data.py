from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from .data import MarketData

_REQUIRED_COLUMNS = [
    "security_id",
    "split_date",
    "settlement_date",
    "settlement_price",
    "settlement_date_available_at",
    "settlement_price_available_at",
    "local_currency",
    "source",
]
_SCHEMA_VERSION = 1
_ALLOWED_CURRENCIES = {"USD", "TWD"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


@dataclass(frozen=True)
class CashInLieuSettlementManifest:
    schema_version: int
    dataset_id: str
    row_count: int
    security_ids: tuple[str, ...]
    file_sha256: str


@dataclass(frozen=True)
class CashInLieuSettlementDataset:
    records: pd.DataFrame

    def __post_init__(self) -> None:
        missing = [column for column in _REQUIRED_COLUMNS if column not in self.records.columns]
        if missing:
            raise ValueError(f"cash-in-lieu settlement data missing columns: {missing}")
        frame = self.records[_REQUIRED_COLUMNS].copy()
        frame["security_id"] = frame["security_id"].map(_text)
        frame["local_currency"] = frame["local_currency"].map(lambda value: _text(value).upper())
        frame["source"] = frame["source"].map(_text)
        for column in (
            "split_date",
            "settlement_date",
            "settlement_date_available_at",
            "settlement_price_available_at",
        ):
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
        frame["settlement_price"] = pd.to_numeric(frame["settlement_price"], errors="coerce")

        if frame["security_id"].eq("").any():
            raise ValueError("security_id cannot be empty")
        if frame["source"].eq("").any():
            raise ValueError("source cannot be empty")
        invalid_currency = sorted(set(frame["local_currency"]) - _ALLOWED_CURRENCIES)
        if invalid_currency:
            raise ValueError(f"unsupported cash-in-lieu currencies: {invalid_currency}")
        required_dates = (
            "split_date",
            "settlement_date",
            "settlement_date_available_at",
            "settlement_price_available_at",
        )
        for column in required_dates:
            if frame[column].isna().any():
                raise ValueError(f"{column} is required")
        invalid_price = (
            frame["settlement_price"].isna()
            | ~np.isfinite(frame["settlement_price"])
            | (frame["settlement_price"] <= 0.0)
        )
        if invalid_price.any():
            raise ValueError("settlement_price must be positive and finite")
        if (frame["settlement_date"] < frame["split_date"]).any():
            raise ValueError("settlement_date cannot precede split_date")
        if (frame["settlement_date_available_at"] > frame["split_date"]).any():
            raise ValueError("settlement date was not known by the split date")
        if (frame["settlement_price_available_at"] > frame["settlement_date"]).any():
            raise ValueError(
                "settlement price was not available by the spendable settlement session"
            )
        if frame.duplicated(["security_id", "split_date"], keep=False).any():
            raise ValueError("duplicate cash-in-lieu settlement key")

        frame = frame.sort_values(["security_id", "split_date"], kind="stable").reset_index(drop=True)
        object.__setattr__(self, "records", frame)

    @property
    def security_ids(self) -> list[str]:
        return list(dict.fromkeys(self.records["security_id"].tolist()))

    def apply_to_market_data(self, data: MarketData, assets: pd.DataFrame) -> MarketData:
        required_asset_columns = {"security_id", "asset_key"}
        if not required_asset_columns.issubset(assets.columns):
            raise ValueError("asset identity table requires security_id and asset_key")
        if assets["security_id"].duplicated().any():
            raise ValueError("asset identity table has duplicate security_id")

        asset_map = dict(zip(assets["security_id"].astype(str), assets["asset_key"].astype(str)))
        settlement_prices = (
            data.cash_in_lieu_prices.copy()
            if data.cash_in_lieu_prices is not None
            else pd.DataFrame(np.nan, index=data.close.index, columns=data.close.columns)
        )
        settlement_dates = (
            data.cash_in_lieu_settlement_dates.copy()
            if data.cash_in_lieu_settlement_dates is not None
            else pd.DataFrame(pd.NaT, index=data.close.index, columns=data.close.columns)
        )
        index = pd.DatetimeIndex(data.close.index)

        for record in self.records.itertuples(index=False):
            asset_key = asset_map.get(str(record.security_id))
            if asset_key is None:
                continue
            if asset_key not in data.symbols:
                raise ValueError(f"asset key missing from market data: {asset_key}")
            split_date = pd.Timestamp(record.split_date)
            settlement_date = pd.Timestamp(record.settlement_date)
            if split_date < index.min() or split_date > index.max():
                continue
            if split_date not in index:
                raise ValueError("cash-in-lieu split_date is not a market-data date")
            ratio = float(data.stock_splits.loc[split_date, asset_key])
            if not np.isfinite(ratio) or ratio <= 0.0 or abs(ratio - 1.0) <= 1e-12:
                raise ValueError(
                    f"cash-in-lieu settlement has no matching split event for {record.security_id}"
                )
            if data.currency_codes is not None:
                observed_currency = data.currency_codes.loc[split_date, asset_key]
                if pd.notna(observed_currency) and str(observed_currency) != record.local_currency:
                    raise ValueError(
                        f"cash-in-lieu currency mismatch for {record.security_id}"
                    )

            existing_date = settlement_dates.loc[split_date, asset_key]
            if pd.notna(existing_date) and pd.Timestamp(existing_date) != settlement_date:
                raise ValueError("cash-in-lieu settlement-date panel conflict")
            settlement_dates.loc[split_date, asset_key] = settlement_date

            if settlement_date <= index.max():
                if settlement_date not in index:
                    raise ValueError(
                        "cash-in-lieu settlement date must be present when inside market-data range"
                    )
                existing_price = settlement_prices.loc[settlement_date, asset_key]
                price = float(record.settlement_price)
                if pd.notna(existing_price) and not np.isclose(float(existing_price), price):
                    raise ValueError("cash-in-lieu settlement-price panel conflict")
                settlement_prices.loc[settlement_date, asset_key] = price

        return replace(
            data,
            cash_in_lieu_prices=settlement_prices,
            cash_in_lieu_settlement_dates=settlement_dates,
        )


@dataclass(frozen=True)
class CashInLieuCSVProvider:
    source: str
    column_map: dict[str, str] | None = None

    def load(self, path: str | Path) -> CashInLieuSettlementDataset:
        frame = pd.read_csv(path).rename(columns=self.column_map or {})
        if "source" not in frame.columns:
            frame["source"] = self.source
        else:
            frame["source"] = frame["source"].map(_text)
            frame.loc[frame["source"].eq(""), "source"] = self.source
        return CashInLieuSettlementDataset(frame)


def save_cash_in_lieu_settlement_dataset(
    dataset: CashInLieuSettlementDataset,
    directory: str | Path,
) -> CashInLieuSettlementManifest:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    data_path = root / "cash_in_lieu_settlements.parquet"
    dataset.records.to_parquet(data_path, engine="pyarrow", compression="zstd", index=False)
    file_hash = _sha256(data_path)
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "row_count": len(dataset.records),
        "security_ids": dataset.security_ids,
        "file_sha256": file_hash,
    }
    dataset_id = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest = CashInLieuSettlementManifest(
        schema_version=_SCHEMA_VERSION,
        dataset_id=dataset_id,
        row_count=len(dataset.records),
        security_ids=tuple(dataset.security_ids),
        file_sha256=file_hash,
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": manifest.schema_version,
                "dataset_id": manifest.dataset_id,
                "row_count": manifest.row_count,
                "security_ids": list(manifest.security_ids),
                "file_sha256": manifest.file_sha256,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return manifest


def load_cash_in_lieu_settlement_dataset(
    directory: str | Path,
) -> tuple[CashInLieuSettlementDataset, CashInLieuSettlementManifest]:
    root = Path(directory)
    raw = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if int(raw.get("schema_version", -1)) != _SCHEMA_VERSION:
        raise ValueError("unsupported cash-in-lieu settlement schema version")
    data_path = root / "cash_in_lieu_settlements.parquet"
    observed_hash = _sha256(data_path)
    expected_hash = str(raw["file_sha256"])
    if observed_hash != expected_hash:
        raise ValueError("cash-in-lieu settlement file hash mismatch")
    payload = {
        "schema_version": int(raw["schema_version"]),
        "row_count": int(raw["row_count"]),
        "security_ids": list(raw["security_ids"]),
        "file_sha256": expected_hash,
    }
    dataset_id = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if dataset_id != raw["dataset_id"]:
        raise ValueError("cash-in-lieu settlement dataset ID mismatch")

    dataset = CashInLieuSettlementDataset(pd.read_parquet(data_path))
    manifest = CashInLieuSettlementManifest(
        schema_version=_SCHEMA_VERSION,
        dataset_id=dataset_id,
        row_count=int(raw["row_count"]),
        security_ids=tuple(raw["security_ids"]),
        file_sha256=expected_hash,
    )
    if len(dataset.records) != manifest.row_count:
        raise ValueError("cash-in-lieu settlement manifest row-count mismatch")
    if tuple(dataset.security_ids) != manifest.security_ids:
        raise ValueError("cash-in-lieu settlement manifest identity mismatch")
    return dataset, manifest
