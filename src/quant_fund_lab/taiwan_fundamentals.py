from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from .fundamentals import FundamentalDataset

_FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
_FINMIND_CREATE_TIME_INITIALIZATION_DATE = pd.Timestamp("2026-04-21")

FINMIND_METRIC_MAP: dict[str, str] = {
    "IncomeAfterTaxes": "net_income",
    "OperatingIncome": "operating_income",
    "GrossProfit": "gross_profit",
    "EPS": "eps",
    "CashFlowsFromOperatingActivities": "operating_cash_flow",
    "CashProvidedByInvestingActivities": "investing_cash_flow",
    "CashProvidedByFinancingActivities": "financing_cash_flow",
    "CashBalancesEndOfPeriod": "cash",
}


def _symbol_for(stock_id: str, symbol_map: dict[str, str] | None) -> str:
    return symbol_map.get(stock_id, stock_id) if symbol_map else stock_id


def _fiscal_period(period_end: pd.Timestamp) -> str:
    quarter = max(1, min(4, (period_end.month - 1) // 3 + 1))
    return f"Q{quarter}"


def normalize_finmind_statement(
    raw: pd.DataFrame,
    availability: pd.DataFrame,
    dataset_name: str,
    symbol_map: dict[str, str] | None = None,
) -> FundamentalDataset:
    """Normalize FinMind statement rows only when an explicit historical availability date exists."""

    required_raw = {"date", "stock_id", "type", "value"}
    required_availability = {"stock_id", "period_end", "available_at"}
    if not required_raw.issubset(raw.columns):
        raise ValueError(f"FinMind raw data missing columns: {sorted(required_raw - set(raw.columns))}")
    if not required_availability.issubset(availability.columns):
        raise ValueError(
            "Taiwan statements require stock_id/period_end/available_at availability mapping"
        )
    source = raw.copy()
    source["period_end"] = pd.to_datetime(source["date"], errors="coerce")
    calendar = availability.copy()
    calendar["period_end"] = pd.to_datetime(calendar["period_end"], errors="coerce")
    calendar["available_at"] = pd.to_datetime(calendar["available_at"], errors="coerce")
    if calendar["available_at"].isna().any():
        raise ValueError("availability mapping contains invalid available_at")
    merged = source.merge(
        calendar[["stock_id", "period_end", "available_at"]],
        on=["stock_id", "period_end"],
        how="left",
        validate="many_to_one",
    )
    if merged["available_at"].isna().any():
        missing = merged.loc[merged["available_at"].isna(), ["stock_id", "period_end"]]
        preview = missing.drop_duplicates().head(5).to_dict("records")
        raise ValueError(f"missing point-in-time availability mapping for Taiwan statements: {preview}")
    rows: list[dict[str, object]] = []
    for row in merged.itertuples(index=False):
        stock_id = str(row.stock_id)
        period_end = pd.Timestamp(row.period_end)
        raw_type = str(row.type)
        metric = FINMIND_METRIC_MAP.get(raw_type, f"finmind:{raw_type}")
        rows.append(
            {
                "symbol": _symbol_for(stock_id, symbol_map),
                "metric": metric,
                "value": row.value,
                "unit": "TWD",
                "period_start": None,
                "period_end": period_end,
                "filed_at": pd.Timestamp(row.available_at),
                "form": dataset_name,
                "accession": f"{dataset_name}:{stock_id}:{period_end.date()}:{raw_type}",
                "fiscal_year": period_end.year,
                "fiscal_period": _fiscal_period(period_end),
                "source": f"finmind:{dataset_name}:external_availability",
            }
        )
    return FundamentalDataset(pd.DataFrame(rows))


def normalize_finmind_month_revenue(
    raw: pd.DataFrame,
    symbol_map: dict[str, str] | None = None,
    allow_initialization_backfill: bool = False,
) -> FundamentalDataset:
    """Use FinMind create_time as an observed-availability proxy, never as an official filing time."""

    required = {"date", "stock_id", "revenue", "create_time"}
    if not required.issubset(raw.columns):
        raise ValueError(f"month revenue missing columns: {sorted(required - set(raw.columns))}")
    frame = raw.copy()
    frame["period_end"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["available_at"] = pd.to_datetime(frame["create_time"], errors="coerce")
    frame = frame[frame["available_at"].notna()].copy()
    if not allow_initialization_backfill:
        frame = frame[frame["available_at"] != _FINMIND_CREATE_TIME_INITIALIZATION_DATE]
    rows: list[dict[str, object]] = []
    for row in frame.itertuples(index=False):
        stock_id = str(row.stock_id)
        period_end = pd.Timestamp(row.period_end)
        rows.append(
            {
                "symbol": _symbol_for(stock_id, symbol_map),
                "metric": "monthly_revenue",
                "value": row.revenue,
                "unit": "TWD",
                "period_start": None,
                "period_end": period_end,
                "filed_at": pd.Timestamp(row.available_at),
                "form": "TaiwanStockMonthRevenue",
                "accession": f"TaiwanStockMonthRevenue:{stock_id}:{period_end.date()}",
                "fiscal_year": getattr(row, "revenue_year", period_end.year),
                "fiscal_period": f"M{getattr(row, 'revenue_month', period_end.month):02d}",
                "source": "finmind:TaiwanStockMonthRevenue:create_time_proxy",
            }
        )
    return FundamentalDataset(pd.DataFrame(rows, columns=[
        "symbol", "metric", "value", "unit", "period_start", "period_end", "filed_at",
        "form", "accession", "fiscal_year", "fiscal_period", "source"
    ]))


@dataclass
class FinMindFundamentalProvider:
    token: str | None = None
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        self.token = self.token or os.environ.get("FINMIND_TOKEN")

    def query(
        self,
        dataset: str,
        stock_id: str,
        start_date: str,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        params = {"dataset": dataset, "data_id": stock_id, "start_date": start_date}
        if end_date is not None:
            params["end_date"] = end_date
        request = Request(f"{_FINMIND_URL}?{urlencode(params)}", headers={"Accept": "application/json"})
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload: dict[str, Any] = json.loads(response.read())
        if payload.get("status") not in (None, 200):
            raise RuntimeError(f"FinMind API error: {payload.get('msg', payload.get('status'))}")
        return pd.DataFrame(payload.get("data", []))

    def financial_statement_raw(self, stock_id: str, start_date: str, end_date: str | None = None) -> pd.DataFrame:
        return self.query("TaiwanStockFinancialStatements", stock_id, start_date, end_date)

    def balance_sheet_raw(self, stock_id: str, start_date: str, end_date: str | None = None) -> pd.DataFrame:
        return self.query("TaiwanStockBalanceSheet", stock_id, start_date, end_date)

    def cash_flow_raw(self, stock_id: str, start_date: str, end_date: str | None = None) -> pd.DataFrame:
        return self.query("TaiwanStockCashFlowsStatement", stock_id, start_date, end_date)

    def month_revenue_raw(self, stock_id: str, start_date: str, end_date: str | None = None) -> pd.DataFrame:
        return self.query("TaiwanStockMonthRevenue", stock_id, start_date, end_date)
