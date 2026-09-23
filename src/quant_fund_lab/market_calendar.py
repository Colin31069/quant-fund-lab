from __future__ import annotations

from dataclasses import dataclass

import exchange_calendars as xcals
import pandas as pd

from .data import MarketData


@dataclass(frozen=True)
class SessionValidation:
    market: str
    observed_sessions: int
    expected_sessions: int
    missing_sessions: tuple[pd.Timestamp, ...]
    off_calendar_sessions: tuple[pd.Timestamp, ...]

    @property
    def is_valid(self) -> bool:
        return not self.missing_sessions and not self.off_calendar_sessions


def _calendar_name(market: str) -> str:
    names = {"US": "XNYS", "TW": "XTAI"}
    try:
        return names[market]
    except KeyError as exc:
        raise ValueError(f"unsupported market calendar: {market}") from exc


def validate_daily_sessions(index: pd.DatetimeIndex, market: str) -> SessionValidation:
    if index.empty:
        raise ValueError("cannot validate an empty session index")
    observed = pd.DatetimeIndex(index).tz_localize(None).normalize().unique().sort_values()
    calendar = xcals.get_calendar(_calendar_name(market))
    expected = calendar.sessions_in_range(observed[0], observed[-1]).tz_localize(None).normalize()
    missing = expected.difference(observed)
    off_calendar = observed.difference(expected)
    return SessionValidation(
        market=market,
        observed_sessions=len(observed),
        expected_sessions=len(expected),
        missing_sessions=tuple(pd.Timestamp(x) for x in missing),
        off_calendar_sessions=tuple(pd.Timestamp(x) for x in off_calendar),
    )


def require_valid_daily_sessions(index: pd.DatetimeIndex, market: str) -> SessionValidation:
    report = validate_daily_sessions(index, market)
    weekend = tuple(x for x in report.off_calendar_sessions if x.weekday() >= 5)
    if weekend:
        dates = ", ".join(str(x.date()) for x in weekend[:5])
        raise ValueError(f"{market} data contains weekend sessions: {dates}")
    return report


def validate_point_in_time_market_sessions(
    data: MarketData,
) -> dict[str, SessionValidation]:
    """Validate real observations against each asset's point-in-time market calendar.

    Cross-market union dates are not observations for a closed market unless that market actually
    has a positive-volume or non-null open on the date. Forward-filled closes therefore do not turn
    another market's session into a false local session.
    """

    if data.market_codes is None:
        raise ValueError("point-in-time session validation requires market_codes")
    active = data.membership.fillna(False)
    observed_bar = data.open.notna() | data.volume.fillna(0.0).gt(0.0)
    reports: dict[str, SessionValidation] = {}
    markets = sorted(set(data.market_codes.stack().astype(str)))
    for market in markets:
        assigned = active & data.market_codes.eq(market)
        active_dates = pd.DatetimeIndex(data.close.index[assigned.any(axis=1)])
        if active_dates.empty:
            continue
        observed_dates = pd.DatetimeIndex(data.close.index[(assigned & observed_bar).any(axis=1)])
        calendar = xcals.get_calendar(_calendar_name(market))
        start = pd.Timestamp(active_dates.min()).tz_localize(None).normalize()
        end = pd.Timestamp(active_dates.max()).tz_localize(None).normalize()
        expected = calendar.sessions_in_range(start, end).tz_localize(None).normalize()
        observed = (
            observed_dates.tz_localize(None).normalize().unique().sort_values()
            if not observed_dates.empty
            else pd.DatetimeIndex([])
        )
        missing = expected.difference(observed)
        off_calendar = observed.difference(expected)
        reports[market] = SessionValidation(
            market=market,
            observed_sessions=len(observed),
            expected_sessions=len(expected),
            missing_sessions=tuple(pd.Timestamp(value) for value in missing),
            off_calendar_sessions=tuple(pd.Timestamp(value) for value in off_calendar),
        )
    return reports


def require_point_in_time_market_sessions(
    data: MarketData,
) -> dict[str, SessionValidation]:
    reports = validate_point_in_time_market_sessions(data)
    for market, report in reports.items():
        weekend = tuple(date for date in report.off_calendar_sessions if date.weekday() >= 5)
        if weekend:
            dates = ", ".join(str(date.date()) for date in weekend[:5])
            raise ValueError(f"{market} data contains weekend sessions: {dates}")
    return reports
