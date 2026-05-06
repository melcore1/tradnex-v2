"""Date / trading-calendar utilities.

US equity holidays are computed from rules (fixed dates + nth-weekday +
Easter-derived Good Friday). The list is comprehensive for NYSE/NASDAQ but
doesn't yet handle "observed" shifts when a holiday falls on a weekend
(those are explicitly modeled here as well, since markets shift the
observed close to the nearest weekday).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def today_et() -> str:
    """Returns 'YYYY-MM-DD' for the current date in US/Eastern."""
    return datetime.now(ET).date().isoformat()


def _easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm — exact Easter Sunday for any Gregorian year."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _good_friday(year: int) -> date:
    return _easter_sunday(year) - timedelta(days=2)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The nth occurrence of a given weekday (0=Mon..6=Sun) in a month."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """The last occurrence of a given weekday in a month."""
    if month == 12:
        last_day = date(year, 12, 31)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)
    offset = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=offset)


def _observed(d: date) -> date:
    """NYSE rule: holiday on Sat → observed Fri, on Sun → observed Mon."""
    if d.weekday() == 5:  # Saturday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday
        return d + timedelta(days=1)
    return d


def us_market_holidays(year: int) -> set[date]:
    """All NYSE/NASDAQ closed dates for a given year, with weekend shifts applied."""
    return {
        _observed(date(year, 1, 1)),  # New Year's Day
        _nth_weekday(year, 1, 0, 3),  # MLK Day — 3rd Mon Jan
        _nth_weekday(year, 2, 0, 3),  # Presidents Day — 3rd Mon Feb
        _good_friday(year),
        _last_weekday(year, 5, 0),  # Memorial Day — last Mon May
        _observed(date(year, 6, 19)),  # Juneteenth
        _observed(date(year, 7, 4)),  # Independence Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day — 1st Mon Sep
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving — 4th Thu Nov
        _observed(date(year, 12, 25)),  # Christmas
    }


def is_trading_day(date_str: str) -> bool:
    """True if the date is a US equity trading day (Mon-Fri, not a holiday)."""
    d = date.fromisoformat(date_str)
    if d.weekday() >= 5:
        return False
    return d not in us_market_holidays(d.year)


def previous_trading_day(date_str: str) -> str:
    d = date.fromisoformat(date_str)
    while True:
        d = d - timedelta(days=1)
        if is_trading_day(d.isoformat()):
            return d.isoformat()


def next_trading_day(date_str: str) -> str:
    d = date.fromisoformat(date_str)
    while True:
        d = d + timedelta(days=1)
        if is_trading_day(d.isoformat()):
            return d.isoformat()
