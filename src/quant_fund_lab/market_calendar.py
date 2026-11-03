from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version

import exchange_calendars as xcals
import pandas as pd

from .calendar_corrections import apply_official_closure_corrections
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


@dataclass(frozen=True)
class CalendarSessions:
    """Versioned expected sessions, independent of the observed price rows."""

    market: str
    calendar: str
    revision: str
    sessions: tuple[pd.Timestamp, ...]
    coverage_start: str = ""
    coverage_end: str = ""


@dataclass(frozen=True)
class CalendarClosures:
    """Verified closure snapshot, scoped to a market and explicit evidence coverage.

    The source adapter verifies bytes before constructing this value. Its revision
    identifies that evidence snapshot; it does not certify the source's truth.
    """

    market: str
    revision: str
    coverage_start: str
    coverage_end: str
    sessions: tuple[pd.Timestamp, ...]

    def __post_init__(self) -> None:
        _calendar_name(self.market)
        first, last = pd.Timestamp(self.coverage_start), pd.Timestamp(self.coverage_end)
        if (not self.revision or pd.isna(first) or pd.isna(last) or first > last
                or str(first.date()) != self.coverage_start
                or str(last.date()) != self.coverage_end):
            raise ValueError("closure evidence requires canonical ordered coverage and revision")
        if not isinstance(self.sessions, tuple):
            raise TypeError("closure evidence sessions must be immutable")
        for day in self.sessions:
            if (not isinstance(day, pd.Timestamp) or pd.isna(day)
                    or day.tzinfo is not None or day != day.normalize()):
                raise ValueError("closure evidence sessions must be normalized dates")
        if tuple(sorted(set(self.sessions))) != self.sessions:
            raise ValueError("closure evidence sessions must be unique and ordered")


def expected_market_sessions(
    market: str, start: object, end: object, *, closures: CalendarClosures | None = None,
) -> CalendarSessions:
    """Return the provider's sessions for explicit inclusive date boundaries."""
    name = _calendar_name(market)
    first, last = pd.Timestamp(start), pd.Timestamp(end)
    if pd.isna(first) or pd.isna(last):
        raise ValueError("calendar boundaries must be valid and ordered")
    first = first.tz_localize(None).normalize()
    last = last.tz_localize(None).normalize()
    if first > last:
        raise ValueError("calendar boundaries must be valid and ordered")
    dates = xcals.get_calendar(name).sessions_in_range(first, last)
    dates = dates.tz_localize(None).normalize().unique().sort_values()
    dates, correction_revision = apply_official_closure_corrections(market, name, dates)
    revision = f"exchange-calendars:{version('exchange-calendars')}"
    revision += correction_revision
    if closures is not None:
        if (closures.market != market or str(first.date()) < closures.coverage_start
                or str(last.date()) > closures.coverage_end):
            raise ValueError("closure evidence does not cover requested market and interval")
        dates = dates.difference(pd.DatetimeIndex(closures.sessions))
        revision += ";" + closures.revision
    return CalendarSessions(
        market, name, revision,
        tuple(pd.Timestamp(day) for day in dates), str(first.date()), str(last.date()),
    )


def validate_daily_sessions(
    index: pd.DatetimeIndex, market: str, *, closures: CalendarClosures | None = None,
) -> SessionValidation:
    if index.empty:
        raise ValueError("cannot validate an empty session index")
    observed = pd.DatetimeIndex(index).tz_localize(None).normalize().unique().sort_values()
    expected = pd.DatetimeIndex(expected_market_sessions(
        market, observed[0], observed[-1], closures=closures,
    ).sessions)
    missing = expected.difference(observed)
    off_calendar = observed.difference(expected)
    return SessionValidation(
        market=market,
        observed_sessions=len(observed),
        expected_sessions=len(expected),
        missing_sessions=tuple(pd.Timestamp(x) for x in missing),
        off_calendar_sessions=tuple(pd.Timestamp(x) for x in off_calendar),
    )


def require_valid_daily_sessions(
    index: pd.DatetimeIndex, market: str, *, closures: CalendarClosures | None = None,
) -> SessionValidation:
    report = validate_daily_sessions(index, market, closures=closures)
    weekend = tuple(x for x in report.off_calendar_sessions if x.weekday() >= 5)
    if weekend:
        dates = ", ".join(str(x.date()) for x in weekend[:5])
        raise ValueError(f"{market} data contains weekend sessions: {dates}")
    return report


def validate_point_in_time_market_sessions(
    data: MarketData, *, closures: dict[str, CalendarClosures] | None = None,
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
    for market, evidence in (closures or {}).items():
        if market != evidence.market:
            raise ValueError("closure evidence market mapping conflicts")
    for market in markets:
        assigned = active & data.market_codes.eq(market)
        active_dates = pd.DatetimeIndex(data.close.index[assigned.any(axis=1)])
        if active_dates.empty:
            continue
        observed_dates = pd.DatetimeIndex(data.close.index[(assigned & observed_bar).any(axis=1)])
        start = pd.Timestamp(active_dates.min()).tz_localize(None).normalize()
        end = pd.Timestamp(active_dates.max()).tz_localize(None).normalize()
        expected = pd.DatetimeIndex(expected_market_sessions(
            market, start, end, closures=(closures or {}).get(market),
        ).sessions)
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
    data: MarketData, *, closures: dict[str, CalendarClosures] | None = None,
) -> dict[str, SessionValidation]:
    reports = validate_point_in_time_market_sessions(data, closures=closures)
    for market, report in reports.items():
        weekend = tuple(date for date in report.off_calendar_sessions if date.weekday() >= 5)
        if weekend:
            dates = ", ".join(str(date.date()) for date in weekend[:5])
            raise ValueError(f"{market} data contains weekend sessions: {dates}")
    return reports
