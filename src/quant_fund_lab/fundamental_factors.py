from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .fundamentals import FundamentalDataset

_EPS = 1e-12


@dataclass(frozen=True)
class FundamentalFactorResult:
    panels: dict[str, pd.DataFrame]
    coverage: pd.DataFrame


def _facts_known_by(
    dataset: FundamentalDataset,
    symbol: str,
    metric: str,
    signal_date: pd.Timestamp,
) -> pd.DataFrame:
    frame = dataset.facts
    known = frame[
        (frame["symbol"] == symbol)
        & (frame["metric"] == metric)
        & (frame["filed_at"] <= signal_date)
        & frame["period_end"].notna()
    ].copy()
    if known.empty:
        return known
    known["period_end"] = pd.to_datetime(known["period_end"])
    known["period_start"] = pd.to_datetime(known["period_start"], errors="coerce")
    return known.sort_values(
        ["period_end", "filed_at", "accession"], kind="stable"
    )


def _latest_period_fact(frame: pd.DataFrame) -> pd.Series | None:
    if frame.empty:
        return None
    latest_period = frame["period_end"].max()
    candidates = frame[frame["period_end"] == latest_period]
    return candidates.sort_values(["filed_at", "accession"], kind="stable").iloc[-1]


def _resolved_instant_history(
    dataset: FundamentalDataset,
    symbol: str,
    metric: str,
    signal_date: pd.Timestamp,
) -> pd.DataFrame:
    frame = _facts_known_by(dataset, symbol, metric, signal_date)
    if frame.empty:
        return frame
    return (
        frame.sort_values(["period_end", "filed_at", "accession"], kind="stable")
        .groupby("period_end", as_index=False, sort=True)
        .tail(1)
        .sort_values("period_end")
    )


def _duration_days(row: pd.Series) -> float:
    start = row.get("period_start")
    end = row.get("period_end")
    if pd.isna(start) or pd.isna(end):
        return float("nan")
    return float((pd.Timestamp(end) - pd.Timestamp(start)).days + 1)


def _select_latest_flow(
    dataset: FundamentalDataset,
    symbol: str,
    metric: str,
    signal_date: pd.Timestamp,
) -> pd.Series | None:
    """Select a latest non-overlapping reporting context without mixing YTD and annual rows.

    For annual forms/FY contexts prefer the longest valid duration. For interim filings prefer the
    shortest valid duration at the latest period-end, which selects a discrete quarter when both
    quarter and YTD contexts are present. Unknown-duration rows are intentionally excluded.
    """

    frame = _facts_known_by(dataset, symbol, metric, signal_date)
    if frame.empty:
        return None
    frame = frame.copy()
    frame["duration_days"] = frame.apply(_duration_days, axis=1)
    frame = frame[frame["duration_days"].between(45.0, 400.0)]
    if frame.empty:
        return None
    latest_period = frame["period_end"].max()
    candidates = frame[frame["period_end"] == latest_period].copy()
    candidates["is_annual"] = (
        candidates["fiscal_period"].astype(str).str.upper().eq("FY")
        | candidates["form"].astype(str).str.upper().str.startswith(("10-K", "20-F", "40-F"))
    )
    if bool(candidates["is_annual"].any()):
        candidates = candidates[candidates["is_annual"]]
        target_duration = candidates["duration_days"].max()
    else:
        target_duration = candidates["duration_days"].min()
    candidates = candidates[candidates["duration_days"] == target_duration]
    return candidates.sort_values(["filed_at", "accession"], kind="stable").iloc[-1]


def _annualized_flow(row: pd.Series | None) -> float:
    if row is None:
        return float("nan")
    duration = _duration_days(row)
    if not np.isfinite(duration) or duration <= 0.0:
        return float("nan")
    return float(row["value"]) * 365.0 / duration


def _instant_at_or_before_period(
    dataset: FundamentalDataset,
    symbol: str,
    metric: str,
    signal_date: pd.Timestamp,
    period_end: pd.Timestamp,
) -> pd.Series | None:
    history = _resolved_instant_history(dataset, symbol, metric, signal_date)
    if history.empty:
        return None
    eligible = history[history["period_end"] <= period_end]
    return _latest_period_fact(eligible)


def _latest_common_period_ratio(
    dataset: FundamentalDataset,
    symbol: str,
    numerator_metric: str,
    denominator_metric: str,
    signal_date: pd.Timestamp,
) -> float:
    numerator = _facts_known_by(dataset, symbol, numerator_metric, signal_date)
    denominator = _facts_known_by(dataset, symbol, denominator_metric, signal_date)
    if numerator.empty or denominator.empty:
        return float("nan")
    numerator = numerator.copy()
    denominator = denominator.copy()
    numerator["context_start"] = numerator["period_start"].astype("datetime64[ns]")
    denominator["context_start"] = denominator["period_start"].astype("datetime64[ns]")
    keys = ["period_end", "context_start"]
    left = (
        numerator.sort_values(keys + ["filed_at", "accession"], kind="stable")
        .groupby(keys, dropna=False, as_index=False)
        .tail(1)
    )
    right = (
        denominator.sort_values(keys + ["filed_at", "accession"], kind="stable")
        .groupby(keys, dropna=False, as_index=False)
        .tail(1)
    )
    merged = left.merge(right, on=keys, suffixes=("_num", "_den"))
    if merged.empty:
        return float("nan")
    row = merged.sort_values("period_end").iloc[-1]
    denominator_value = float(row["value_den"])
    if abs(denominator_value) <= _EPS:
        return float("nan")
    return float(row["value_num"]) / denominator_value


def _asset_growth_score(
    dataset: FundamentalDataset,
    symbol: str,
    signal_date: pd.Timestamp,
) -> float:
    history = _resolved_instant_history(dataset, symbol, "assets", signal_date)
    if len(history) < 2:
        return float("nan")
    current = history.iloc[-1]
    current_end = pd.Timestamp(current["period_end"])
    prior = history[history["period_end"] < current_end].copy()
    if prior.empty:
        return float("nan")
    prior["distance"] = (current_end - prior["period_end"]).dt.days
    prior = prior[prior["distance"].between(270, 460)]
    if prior.empty:
        return float("nan")
    previous = prior.iloc[(prior["distance"] - 365).abs().argmin()]
    previous_value = float(previous["value"])
    if abs(previous_value) <= _EPS:
        return float("nan")
    growth = float(current["value"]) / previous_value - 1.0
    return -growth


def _monthly_revenue_yoy(
    dataset: FundamentalDataset,
    symbol: str,
    signal_date: pd.Timestamp,
) -> float:
    history = _resolved_instant_history(dataset, symbol, "monthly_revenue", signal_date)
    if len(history) < 2:
        return float("nan")
    current = history.iloc[-1]
    current_month = pd.Timestamp(current["period_end"]).to_period("M")
    target = current_month - 12
    prior = history[history["period_end"].dt.to_period("M") == target]
    if prior.empty:
        return float("nan")
    previous_value = float(prior.iloc[-1]["value"])
    if abs(previous_value) <= _EPS:
        return float("nan")
    return float(current["value"]) / previous_value - 1.0


def _coverage_frame(panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for name, panel in panels.items():
        counts = panel.notna().sum(axis=1)
        rows.append(
            {
                "factor": name,
                "mean_names": float(counts.mean()) if len(counts) else 0.0,
                "max_names": int(counts.max()) if len(counts) else 0,
                "nonempty_dates": int((counts > 0).sum()),
                "total_dates": len(counts),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["mean_names", "max_names", "nonempty_dates", "total_dates"])
    return pd.DataFrame(rows).set_index("factor").sort_index()


def build_fundamental_factor_panels(
    dataset: FundamentalDataset,
    dates: pd.DatetimeIndex,
    symbols: list[str],
    market_cap_base: pd.DataFrame | None = None,
    fundamental_fx_to_base: pd.DataFrame | None = None,
) -> FundamentalFactorResult:
    """Derive point-in-time financial factors without exposing future filings.

    Price-independent factors are always attempted. Valuation factors are produced only when an
    explicit base-currency market-cap panel is supplied. Book-to-market and earnings-yield also
    require a matching FX panel to convert reported monetary values into that base currency.
    """

    dates = pd.DatetimeIndex(dates)
    panels = {
        name: pd.DataFrame(index=dates, columns=symbols, dtype=float)
        for name in (
            "profitability_roe",
            "profitability_roa",
            "operating_margin",
            "gross_margin",
            "cash_to_assets",
            "conservative_asset_growth",
            "monthly_revenue_yoy",
        )
    }
    if market_cap_base is not None:
        if not market_cap_base.index.equals(dates) or list(market_cap_base.columns) != symbols:
            raise ValueError("market_cap_base must align exactly with dates and symbols")
        panels["small_size"] = -np.log(market_cap_base.where(market_cap_base > 0.0))
        if fundamental_fx_to_base is None:
            raise ValueError(
                "fundamental_fx_to_base is required for book-to-market/earnings-yield valuation"
            )
        if not fundamental_fx_to_base.index.equals(dates) or list(fundamental_fx_to_base.columns) != symbols:
            raise ValueError("fundamental_fx_to_base must align exactly with dates and symbols")
        panels["book_to_market"] = pd.DataFrame(index=dates, columns=symbols, dtype=float)
        panels["earnings_yield"] = pd.DataFrame(index=dates, columns=symbols, dtype=float)

    for signal_date in dates:
        for symbol in symbols:
            net_income = _select_latest_flow(dataset, symbol, "net_income", signal_date)
            annualized_income = _annualized_flow(net_income)
            if net_income is not None:
                period_end = pd.Timestamp(net_income["period_end"])
                equity = _instant_at_or_before_period(
                    dataset, symbol, "equity", signal_date, period_end
                )
                assets = _instant_at_or_before_period(
                    dataset, symbol, "assets", signal_date, period_end
                )
                if equity is not None and abs(float(equity["value"])) > _EPS:
                    panels["profitability_roe"].loc[signal_date, symbol] = (
                        annualized_income / float(equity["value"])
                    )
                if assets is not None and abs(float(assets["value"])) > _EPS:
                    panels["profitability_roa"].loc[signal_date, symbol] = (
                        annualized_income / float(assets["value"])
                    )

            panels["operating_margin"].loc[signal_date, symbol] = _latest_common_period_ratio(
                dataset, symbol, "operating_income", "revenue", signal_date
            )
            panels["gross_margin"].loc[signal_date, symbol] = _latest_common_period_ratio(
                dataset, symbol, "gross_profit", "revenue", signal_date
            )
            cash = _resolved_instant_history(dataset, symbol, "cash", signal_date)
            assets_history = _resolved_instant_history(dataset, symbol, "assets", signal_date)
            if not cash.empty and not assets_history.empty:
                cash_row = cash.iloc[-1]
                compatible_assets = assets_history[
                    assets_history["period_end"] <= pd.Timestamp(cash_row["period_end"])
                ]
                if not compatible_assets.empty:
                    asset_value = float(compatible_assets.iloc[-1]["value"])
                    if abs(asset_value) > _EPS:
                        panels["cash_to_assets"].loc[signal_date, symbol] = (
                            float(cash_row["value"]) / asset_value
                        )
            panels["conservative_asset_growth"].loc[signal_date, symbol] = _asset_growth_score(
                dataset, symbol, signal_date
            )
            panels["monthly_revenue_yoy"].loc[signal_date, symbol] = _monthly_revenue_yoy(
                dataset, symbol, signal_date
            )

            if market_cap_base is not None and fundamental_fx_to_base is not None:
                market_cap = float(market_cap_base.loc[signal_date, symbol])
                fx = float(fundamental_fx_to_base.loc[signal_date, symbol])
                if np.isfinite(market_cap) and market_cap > 0.0 and np.isfinite(fx) and fx > 0.0:
                    equity_latest = _latest_period_fact(
                        _resolved_instant_history(dataset, symbol, "equity", signal_date)
                    )
                    if equity_latest is not None:
                        panels["book_to_market"].loc[signal_date, symbol] = (
                            float(equity_latest["value"]) * fx / market_cap
                        )
                    if np.isfinite(annualized_income):
                        panels["earnings_yield"].loc[signal_date, symbol] = (
                            annualized_income * fx / market_cap
                        )

    return FundamentalFactorResult(panels=panels, coverage=_coverage_frame(panels))
