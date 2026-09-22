from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

_REQUIRED_COLUMNS = [
    "symbol",
    "metric",
    "value",
    "unit",
    "period_start",
    "period_end",
    "filed_at",
    "form",
    "accession",
    "fiscal_year",
    "fiscal_period",
    "source",
]


@dataclass(frozen=True)
class FundamentalDataset:
    facts: pd.DataFrame

    def __post_init__(self) -> None:
        missing = [column for column in _REQUIRED_COLUMNS if column not in self.facts.columns]
        if missing:
            raise ValueError(f"fundamental facts missing columns: {missing}")
        frame = self.facts.copy()
        for column in ("period_start", "period_end", "filed_at"):
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
        if frame["filed_at"].isna().any():
            raise ValueError("filed_at is required for every fundamental fact")
        if frame["symbol"].astype(str).str.len().eq(0).any():
            raise ValueError("fundamental fact symbol cannot be empty")
        if frame["metric"].astype(str).str.len().eq(0).any():
            raise ValueError("fundamental fact metric cannot be empty")
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
        frame = frame[frame["value"].notna()].copy()
        frame = frame.sort_values(
            ["filed_at", "symbol", "metric", "period_end", "accession"],
            kind="stable",
        ).reset_index(drop=True)
        object.__setattr__(self, "facts", frame)

    @property
    def symbols(self) -> list[str]:
        return sorted(self.facts["symbol"].astype(str).unique().tolist())

    @property
    def metrics(self) -> list[str]:
        return sorted(self.facts["metric"].astype(str).unique().tolist())

    def asof(
        self,
        timestamp: object,
        symbols: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> pd.DataFrame:
        """Latest filed observation per symbol/metric as known at timestamp."""

        cutoff = pd.Timestamp(timestamp)
        frame = self.facts[self.facts["filed_at"] <= cutoff]
        if symbols is not None:
            frame = frame[frame["symbol"].isin(symbols)]
        if metrics is not None:
            frame = frame[frame["metric"].isin(metrics)]
        if frame.empty:
            return frame.copy()
        ordered = frame.sort_values(
            ["symbol", "metric", "filed_at", "period_end", "accession"],
            kind="stable",
        )
        return ordered.groupby(["symbol", "metric"], as_index=False, sort=True).tail(1)

    def metric_panel(
        self,
        metric: str,
        dates: pd.DatetimeIndex,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        """Build a point-in-time wide panel without using future filings."""

        selected_symbols = symbols or self.symbols
        result = pd.DataFrame(index=dates, columns=selected_symbols, dtype=float)
        metric_facts = self.facts[self.facts["metric"] == metric]
        for symbol in selected_symbols:
            series = metric_facts[metric_facts["symbol"] == symbol].sort_values("filed_at")
            if series.empty:
                continue
            left = pd.DataFrame({"timestamp": dates}).sort_values("timestamp")
            right = series[["filed_at", "value"]].rename(columns={"filed_at": "timestamp"})
            merged = pd.merge_asof(left, right, on="timestamp", direction="backward")
            result[symbol] = merged["value"].to_numpy(dtype=float)
        return result


def save_fundamental_dataset(dataset: FundamentalDataset, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    dataset.facts.to_parquet(output, engine="pyarrow", compression="zstd", index=False)
    return output


def load_fundamental_dataset(path: str | Path) -> FundamentalDataset:
    return FundamentalDataset(pd.read_parquet(Path(path)))
