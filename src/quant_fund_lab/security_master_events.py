from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .security_master import SecurityMaster

_EVENT_COLUMNS = [
    "security_id",
    "event_at",
    "event_type",
    "symbol",
    "exchange",
    "currency",
    "last_tradable_at",
    "terminal_return",
    "source",
]
_ALLOWED_EVENT_TYPES = {
    "LISTED",
    "TICKER_CHANGED",
    "EXCHANGE_CHANGED",
    "CURRENCY_CHANGED",
    "DELISTED",
}
_EVENT_PRIORITY = {
    "LISTED": 0,
    "EXCHANGE_CHANGED": 1,
    "CURRENCY_CHANGED": 2,
    "TICKER_CHANGED": 3,
    "DELISTED": 4,
}
_TWSE_ALIASES = {"TWSE", "TSE", "TW"}
_TPEX_ALIASES = {"TPEX", "OTC", "TWO"}


def _text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _normalize_exchange(value: object, market: str) -> str:
    exchange = _text(value).upper()
    if market == "TW":
        if exchange in _TWSE_ALIASES:
            return "TWSE"
        if exchange in _TPEX_ALIASES:
            return "TPEX"
    return exchange


def _normalize_symbol(value: object, market: str, exchange: str) -> str:
    symbol = _text(value).upper()
    if not symbol:
        return ""
    if market != "TW" or symbol.endswith((".TW", ".TWO")):
        return symbol
    if exchange == "TWSE":
        return f"{symbol}.TW"
    if exchange == "TPEX":
        return f"{symbol}.TWO"
    return symbol


def normalize_security_event_frame(
    raw: pd.DataFrame,
    market: str,
    source: str,
    column_map: dict[str, str] | None = None,
    default_exchange: str | None = None,
) -> SecurityMasterEventDataset:
    """Normalize an explicit historical lifecycle export without guessing missing dates/returns."""

    market = market.upper().strip()
    if market not in {"US", "TW"}:
        raise ValueError("market must be US or TW")
    frame = raw.rename(columns=column_map or {}).copy()
    required = {"security_id", "event_at", "event_type"}
    if not required.issubset(frame.columns):
        raise ValueError(f"security event data missing columns: {sorted(required - set(frame.columns))}")
    for column in _EVENT_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    frame = frame[_EVENT_COLUMNS]
    frame["security_id"] = frame["security_id"].map(_text)
    frame["event_type"] = frame["event_type"].map(lambda value: _text(value).upper())
    frame["event_at"] = pd.to_datetime(frame["event_at"], errors="coerce")
    frame["last_tradable_at"] = pd.to_datetime(frame["last_tradable_at"], errors="coerce")
    frame["terminal_return"] = pd.to_numeric(frame["terminal_return"], errors="coerce")
    frame["source"] = frame["source"].map(_text)
    frame.loc[frame["source"].eq(""), "source"] = source

    default_exchange_normalized = _normalize_exchange(default_exchange, market)
    frame["_exchange_input"] = frame["exchange"].map(lambda value: _normalize_exchange(value, market))
    frame = frame.sort_values(
        ["security_id", "event_at", "event_type"], kind="stable", na_position="last"
    )
    if default_exchange_normalized:
        frame.loc[frame["_exchange_input"].eq(""), "_exchange_input"] = default_exchange_normalized
    frame["_effective_exchange"] = frame.groupby("security_id", sort=False)["_exchange_input"].transform(
        lambda values: values.replace("", pd.NA).ffill()
    )
    frame["exchange"] = frame["_exchange_input"]
    frame["currency"] = frame["currency"].map(lambda value: _text(value).upper())
    default_currency = "USD" if market == "US" else "TWD"
    listed = frame["event_type"].eq("LISTED")
    frame.loc[listed & frame["currency"].eq(""), "currency"] = default_currency
    frame["symbol"] = [
        _normalize_symbol(symbol, market, _text(exchange))
        for symbol, exchange in zip(frame["symbol"], frame["_effective_exchange"])
    ]
    frame = frame.drop(columns=["_exchange_input", "_effective_exchange"])
    return SecurityMasterEventDataset(frame)


@dataclass(frozen=True)
class SecurityMasterEventDataset:
    events: pd.DataFrame

    def __post_init__(self) -> None:
        missing = [column for column in _EVENT_COLUMNS if column not in self.events.columns]
        if missing:
            raise ValueError(f"security event dataset missing columns: {missing}")
        frame = self.events[_EVENT_COLUMNS].copy()
        frame["security_id"] = frame["security_id"].map(_text)
        frame["event_type"] = frame["event_type"].map(lambda value: _text(value).upper())
        frame["symbol"] = frame["symbol"].map(lambda value: _text(value).upper())
        frame["exchange"] = frame["exchange"].map(lambda value: _text(value).upper())
        frame["currency"] = frame["currency"].map(lambda value: _text(value).upper())
        frame["source"] = frame["source"].map(_text)
        frame["event_at"] = pd.to_datetime(frame["event_at"], errors="coerce")
        frame["last_tradable_at"] = pd.to_datetime(frame["last_tradable_at"], errors="coerce")
        frame["terminal_return"] = pd.to_numeric(frame["terminal_return"], errors="coerce")

        if frame["security_id"].eq("").any():
            raise ValueError("security_id cannot be empty")
        if frame["event_at"].isna().any():
            raise ValueError("event_at is required for every security event")
        if frame["source"].eq("").any():
            raise ValueError("source cannot be empty")
        invalid_types = sorted(set(frame["event_type"]) - _ALLOWED_EVENT_TYPES)
        if invalid_types:
            raise ValueError(f"unsupported security event types: {invalid_types}")
        duplicate_key = frame.duplicated(["security_id", "event_at", "event_type"], keep=False)
        if duplicate_key.any():
            raise ValueError("duplicate security lifecycle event key")
        if bool((frame["terminal_return"].dropna() < -1.0).any()):
            raise ValueError("terminal_return cannot be below -100%")

        priority = frame["event_type"].map(_EVENT_PRIORITY)
        frame = (
            frame.assign(_priority=priority)
            .sort_values(["security_id", "event_at", "_priority"], kind="stable")
            .drop(columns="_priority")
            .reset_index(drop=True)
        )
        for security_id, group in frame.groupby("security_id", sort=False):
            self._validate_lifecycle(security_id, group)
        object.__setattr__(self, "events", frame)

    @staticmethod
    def _validate_lifecycle(security_id: str, group: pd.DataFrame) -> None:
        listed = group[group["event_type"].eq("LISTED")]
        if len(listed) != 1:
            raise ValueError(f"{security_id} requires exactly one LISTED event")
        listed_row = listed.iloc[0]
        if pd.Timestamp(listed_row["event_at"]) != pd.Timestamp(group["event_at"].min()):
            raise ValueError(f"{security_id} LISTED must be the first lifecycle event")
        for field in ("symbol", "exchange", "currency"):
            if not _text(listed_row[field]):
                raise ValueError(f"{security_id} LISTED requires {field}")

        delisted = group[group["event_type"].eq("DELISTED")]
        if len(delisted) > 1:
            raise ValueError(f"{security_id} cannot have multiple DELISTED events")
        if len(delisted):
            row = delisted.iloc[0]
            if pd.Timestamp(row["event_at"]) != pd.Timestamp(group["event_at"].max()):
                raise ValueError(f"{security_id} cannot have events after DELISTED")
            if pd.isna(row["last_tradable_at"]):
                raise ValueError(f"{security_id} DELISTED requires last_tradable_at")
            if pd.isna(row["terminal_return"]):
                raise ValueError(f"{security_id} DELISTED requires terminal_return")
            if pd.Timestamp(row["last_tradable_at"]) >= pd.Timestamp(row["event_at"]):
                raise ValueError("last_tradable_at must precede DELISTED event_at")
            if pd.Timestamp(row["last_tradable_at"]) < pd.Timestamp(listed_row["event_at"]):
                raise ValueError("last_tradable_at cannot precede LISTED event_at")

        required_field = {
            "TICKER_CHANGED": "symbol",
            "EXCHANGE_CHANGED": "exchange",
            "CURRENCY_CHANGED": "currency",
        }
        for event_type, field in required_field.items():
            rows = group[group["event_type"].eq(event_type)]
            if rows[field].map(_text).eq("").any():
                raise ValueError(f"{security_id} {event_type} requires {field}")

        non_terminal = ~group["event_type"].eq("DELISTED")
        if group.loc[non_terminal, "last_tradable_at"].notna().any():
            raise ValueError("last_tradable_at is only valid on DELISTED events")
        if group.loc[non_terminal, "terminal_return"].notna().any():
            raise ValueError("terminal_return is only valid on DELISTED events")

    @property
    def security_ids(self) -> list[str]:
        return list(dict.fromkeys(self.events["security_id"].tolist()))

    def materialize(self, as_of: object | None = None) -> SecurityMaster:
        cutoff = None if as_of is None else pd.Timestamp(as_of)
        rows: list[dict[str, object]] = []
        for security_id, full_group in self.events.groupby("security_id", sort=False):
            group = full_group
            if cutoff is not None:
                group = group[group["event_at"] <= cutoff]
            if group.empty or not group["event_type"].eq("LISTED").any():
                continue
            listed = group[group["event_type"].eq("LISTED")].iloc[0]
            symbol = str(listed["symbol"])
            exchange = str(listed["exchange"])
            currency = str(listed["currency"])
            tradable_until: object = pd.NaT
            terminal_event_at: object = pd.NaT
            terminal_return = float("nan")
            for event in group.itertuples(index=False):
                if event.event_type == "TICKER_CHANGED":
                    symbol = str(event.symbol)
                elif event.event_type == "EXCHANGE_CHANGED":
                    exchange = str(event.exchange)
                elif event.event_type == "CURRENCY_CHANGED":
                    currency = str(event.currency)
                elif event.event_type == "DELISTED":
                    tradable_until = pd.Timestamp(event.last_tradable_at)
                    terminal_event_at = pd.Timestamp(event.event_at)
                    terminal_return = float(event.terminal_return)
            rows.append(
                {
                    "security_id": security_id,
                    "symbol": symbol,
                    "exchange": exchange,
                    "currency": currency,
                    "tradable_from": pd.Timestamp(listed["event_at"]),
                    "tradable_until": tradable_until,
                    "terminal_event_at": terminal_event_at,
                    "terminal_return": terminal_return,
                    "source": "|".join(dict.fromkeys(group["source"].astype(str))),
                }
            )
        return SecurityMaster(pd.DataFrame(rows, columns=[
            "security_id",
            "symbol",
            "exchange",
            "currency",
            "tradable_from",
            "tradable_until",
            "terminal_event_at",
            "terminal_return",
            "source",
        ]))

    def identity_history(self) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        for security_id, group in self.events.groupby("security_id", sort=False):
            listed = group[group["event_type"].eq("LISTED")].iloc[0]
            symbol = str(listed["symbol"])
            exchange = str(listed["exchange"])
            currency = str(listed["currency"])
            effective_from = pd.Timestamp(listed["event_at"])
            source_event_type = "LISTED"
            for event in group.iloc[1:].itertuples(index=False):
                if event.event_type == "DELISTED":
                    rows.append(
                        {
                            "security_id": security_id,
                            "symbol": symbol,
                            "exchange": exchange,
                            "currency": currency,
                            "effective_from": effective_from,
                            "effective_until_exclusive": pd.Timestamp(event.event_at),
                            "source_event_type": source_event_type,
                        }
                    )
                    effective_from = pd.NaT
                    break
                if event.event_type not in {
                    "TICKER_CHANGED",
                    "EXCHANGE_CHANGED",
                    "CURRENCY_CHANGED",
                }:
                    continue
                rows.append(
                    {
                        "security_id": security_id,
                        "symbol": symbol,
                        "exchange": exchange,
                        "currency": currency,
                        "effective_from": effective_from,
                        "effective_until_exclusive": pd.Timestamp(event.event_at),
                        "source_event_type": source_event_type,
                    }
                )
                if event.event_type == "TICKER_CHANGED":
                    symbol = str(event.symbol)
                elif event.event_type == "EXCHANGE_CHANGED":
                    exchange = str(event.exchange)
                else:
                    currency = str(event.currency)
                effective_from = pd.Timestamp(event.event_at)
                source_event_type = str(event.event_type)
            if pd.notna(effective_from):
                rows.append(
                    {
                        "security_id": security_id,
                        "symbol": symbol,
                        "exchange": exchange,
                        "currency": currency,
                        "effective_from": effective_from,
                        "effective_until_exclusive": pd.NaT,
                        "source_event_type": source_event_type,
                    }
                )
        return pd.DataFrame(rows)

    def identity_at(self, security_id: str, at: object) -> pd.Series:
        timestamp = pd.Timestamp(at)
        history = self.identity_history()
        rows = history[history["security_id"].eq(str(security_id).strip())]
        active = rows[
            (rows["effective_from"] <= timestamp)
            & (
                rows["effective_until_exclusive"].isna()
                | (timestamp < rows["effective_until_exclusive"])
            )
        ]
        if len(active) != 1:
            raise KeyError(f"no unique identity for {security_id} at {timestamp.date()}")
        return active.iloc[0]


@dataclass(frozen=True)
class SecurityEventCSVProvider:
    market: str
    source: str
    column_map: dict[str, str] | None = None
    default_exchange: str | None = None

    def load(self, path: str | Path) -> SecurityMasterEventDataset:
        raw = pd.read_csv(path)
        return normalize_security_event_frame(
            raw,
            market=self.market,
            source=self.source,
            column_map=self.column_map,
            default_exchange=self.default_exchange,
        )


def merge_security_event_datasets(
    *datasets: SecurityMasterEventDataset,
) -> SecurityMasterEventDataset:
    if not datasets:
        return SecurityMasterEventDataset(pd.DataFrame(columns=_EVENT_COLUMNS))
    return SecurityMasterEventDataset(
        pd.concat([dataset.events for dataset in datasets], ignore_index=True)
    )
