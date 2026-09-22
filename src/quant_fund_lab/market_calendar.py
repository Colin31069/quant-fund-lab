from __future__ import annotations

from dataclasses import dataclass

import exchange_calendars as xcals
import pandas as pd


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
