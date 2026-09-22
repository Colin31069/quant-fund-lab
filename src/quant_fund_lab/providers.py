from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd

from .data import MarketData, download_yahoo
from .snapshot import load_market_data_snapshot


class MarketDataProvider(Protocol):
    name: str

    def load(self, symbols: list[str], start: str, end: str) -> MarketData:
        ...


@dataclass(frozen=True)
class ProviderAttempt:
    provider: str
    success: bool
    error: str | None = None


@dataclass(frozen=True)
class ProviderLoadResult:
    data: MarketData
    provider: str
    attempts: tuple[ProviderAttempt, ...]


@dataclass(frozen=True)
class YahooProvider:
    name: str = "yahoo"

    def load(self, symbols: list[str], start: str, end: str) -> MarketData:
        return download_yahoo(symbols, start, end)


def _subset_market_data(data: MarketData, symbols: list[str], start: str, end: str) -> MarketData:
    missing = [symbol for symbol in symbols if symbol not in data.symbols]
    if missing:
        raise ValueError(f"snapshot is missing requested symbols: {missing}")
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    index = data.close.index[(data.close.index >= start_ts) & (data.close.index < end_ts)]
    if index.empty:
        raise ValueError("snapshot does not contain requested date range")

    def subset(frame: pd.DataFrame | None) -> pd.DataFrame | None:
        return None if frame is None else frame.loc[index, symbols]

    return MarketData(
        open=data.open.loc[index, symbols],
        close=data.close.loc[index, symbols],
        volume=data.volume.loc[index, symbols],
        reference=subset(data.reference),
        membership=subset(data.membership),
        terminal_returns=subset(data.terminal_returns),
        dividends=subset(data.dividends),
        stock_splits=subset(data.stock_splits),
        fx_to_base=subset(data.fx_to_base),
        fx_age_days=subset(data.fx_age_days),
        base_currency=data.base_currency,
        exchange=data.exchange,
    )


@dataclass(frozen=True)
class SnapshotProvider:
    roots: tuple[str | Path, ...]
    name: str = "verified_snapshot"

    def _candidates(self) -> list[Path]:
        candidates: list[Path] = []
        for root_value in self.roots:
            root = Path(root_value)
            if (root / "manifest.json").exists():
                candidates.append(root)
            elif root.exists():
                candidates.extend(path.parent for path in root.rglob("manifest.json"))
        return sorted(set(candidates), key=lambda path: str(path), reverse=True)

    def load(self, symbols: list[str], start: str, end: str) -> MarketData:
        requested_start = pd.Timestamp(start).date()
        errors: list[str] = []
        for directory in self._candidates():
            try:
                manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
                available_symbols = set(manifest.get("symbols", []))
                if not set(symbols).issubset(available_symbols):
                    continue
                if pd.Timestamp(manifest["start"]).date() > requested_start:
                    continue
                data = load_market_data_snapshot(directory)
                return _subset_market_data(data, symbols, start, end)
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                errors.append(f"{directory}: {exc}")
        detail = "; ".join(errors[-3:]) if errors else "no covering verified snapshots"
        raise ValueError(f"snapshot fallback unavailable: {detail}")


def load_with_failover(
    providers: list[MarketDataProvider],
    symbols: list[str],
    start: str,
    end: str,
) -> ProviderLoadResult:
    if not providers:
        raise ValueError("at least one market-data provider is required")
    attempts: list[ProviderAttempt] = []
    for provider in providers:
        try:
            data = provider.load(symbols, start, end)
            attempts.append(ProviderAttempt(provider=provider.name, success=True))
            return ProviderLoadResult(data=data, provider=provider.name, attempts=tuple(attempts))
        except Exception as exc:  # noqa: BLE001 - provider boundary must isolate external failures.
            attempts.append(
                ProviderAttempt(provider=provider.name, success=False, error=f"{type(exc).__name__}: {exc}")
            )
    summary = " | ".join(f"{item.provider}: {item.error}" for item in attempts)
    raise RuntimeError(f"all market-data providers failed: {summary}")
