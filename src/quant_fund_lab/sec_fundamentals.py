from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

import pandas as pd

from .fundamentals import FundamentalDataset

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
_ALLOWED_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A"}

DEFAULT_SEC_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_income": ("OperatingIncomeLoss",),
    "assets": ("Assets",),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "cash": ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    "shares_outstanding": ("CommonStockSharesOutstanding",),
}


def _normalize_ticker_mapping(payload: dict[str, Any]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for value in payload.values():
        ticker = str(value.get("ticker", "")).upper().strip()
        cik = value.get("cik_str")
        if ticker and cik is not None:
            mapping[ticker] = int(cik)
    return mapping


def parse_companyfacts(
    symbol: str,
    payload: dict[str, Any],
    concept_map: dict[str, tuple[str, ...]] | None = None,
) -> FundamentalDataset:
    """Normalize SEC companyfacts into a filing-time point-in-time event table."""

    concepts = concept_map or DEFAULT_SEC_CONCEPTS
    us_gaap = payload.get("facts", {}).get("us-gaap", {})
    rows: list[dict[str, object]] = []
    for metric, candidates in concepts.items():
        concept_data: dict[str, Any] | None = None
        concept_name: str | None = None
        for candidate in candidates:
            if candidate in us_gaap:
                concept_name = candidate
                concept_data = us_gaap[candidate]
                break
        if concept_data is None or concept_name is None:
            continue
        units = concept_data.get("units", {})
        for unit, observations in units.items():
            for observation in observations:
                form = str(observation.get("form", ""))
                if form not in _ALLOWED_FORMS or "filed" not in observation:
                    continue
                rows.append(
                    {
                        "symbol": symbol.upper(),
                        "metric": metric,
                        "value": observation.get("val"),
                        "unit": str(unit),
                        "period_start": observation.get("start"),
                        "period_end": observation.get("end"),
                        "filed_at": observation.get("filed"),
                        "form": form,
                        "accession": str(observation.get("accn", "")),
                        "fiscal_year": observation.get("fy"),
                        "fiscal_period": observation.get("fp"),
                        "source": f"sec:{concept_name}",
                    }
                )
    return FundamentalDataset(pd.DataFrame(rows, columns=[
        "symbol", "metric", "value", "unit", "period_start", "period_end", "filed_at",
        "form", "accession", "fiscal_year", "fiscal_period", "source"
    ]))


@dataclass
class SecCompanyFactsProvider:
    """Official SEC EDGAR companyfacts adapter with declared User-Agent and rate moderation."""

    user_agent: str | None = None
    timeout_seconds: float = 20.0
    min_interval_seconds: float = 0.12

    def __post_init__(self) -> None:
        self.user_agent = self.user_agent or os.environ.get("QFL_SEC_USER_AGENT")
        if not self.user_agent or "@" not in self.user_agent:
            raise ValueError(
                "SEC requires a declared User-Agent with contact information; set QFL_SEC_USER_AGENT"
            )
        self._last_request_at = 0.0
        self._ticker_mapping: dict[str, int] | None = None

    def _json(self, url: str) -> dict[str, Any]:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)
        request = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            body = response.read()
        self._last_request_at = time.monotonic()
        return json.loads(body)

    def ticker_mapping(self, refresh: bool = False) -> dict[str, int]:
        if self._ticker_mapping is None or refresh:
            self._ticker_mapping = _normalize_ticker_mapping(self._json(_TICKERS_URL))
        return dict(self._ticker_mapping)

    def resolve_cik(self, ticker: str) -> int:
        normalized = ticker.upper().strip()
        mapping = self.ticker_mapping()
        if normalized not in mapping:
            raise KeyError(f"SEC CIK mapping not found for ticker {normalized}")
        return mapping[normalized]

    def fetch_companyfacts(self, ticker: str) -> dict[str, Any]:
        cik = self.resolve_cik(ticker)
        return self._json(_COMPANYFACTS_URL.format(cik=cik))

    def fetch(
        self,
        tickers: list[str],
        concept_map: dict[str, tuple[str, ...]] | None = None,
    ) -> FundamentalDataset:
        frames: list[pd.DataFrame] = []
        for ticker in dict.fromkeys(symbol.upper().strip() for symbol in tickers if symbol.strip()):
            parsed = parse_companyfacts(ticker, self.fetch_companyfacts(ticker), concept_map)
            frames.append(parsed.facts)
        if not frames:
            return FundamentalDataset(pd.DataFrame(columns=[
                "symbol", "metric", "value", "unit", "period_start", "period_end", "filed_at",
                "form", "accession", "fiscal_year", "fiscal_period", "source"
            ]))
        return FundamentalDataset(pd.concat(frames, ignore_index=True))
