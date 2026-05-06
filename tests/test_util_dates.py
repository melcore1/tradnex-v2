"""Date utility tests."""

import re
from datetime import date

from shared.util.dates import (
    is_trading_day,
    next_trading_day,
    previous_trading_day,
    today_et,
    us_market_holidays,
)


def test_today_et_format() -> None:
    out = today_et()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", out) is not None


def test_is_trading_day_excludes_weekends() -> None:
    assert is_trading_day("2026-05-02") is False  # Saturday
    assert is_trading_day("2026-05-03") is False  # Sunday
    assert is_trading_day("2026-05-04") is True  # Monday


def test_is_trading_day_excludes_holidays() -> None:
    # 2026 known holidays
    assert is_trading_day("2026-01-01") is False  # New Year's
    assert is_trading_day("2026-07-03") is False  # Independence Day observed (Jul 4 = Sat)
    assert is_trading_day("2026-12-25") is False  # Christmas


def test_us_market_holidays_includes_known_2026() -> None:
    holidays_2026 = us_market_holidays(2026)
    assert date(2026, 1, 1) in holidays_2026
    assert date(2026, 6, 19) in holidays_2026  # Juneteenth
    assert date(2026, 12, 25) in holidays_2026


def test_previous_trading_day_skips_weekend() -> None:
    # 2026-05-04 is Monday → previous trading day is Friday 2026-05-01
    assert previous_trading_day("2026-05-04") == "2026-05-01"


def test_next_trading_day_skips_weekend() -> None:
    # 2026-05-01 is Friday → next trading day is Monday 2026-05-04
    assert next_trading_day("2026-05-01") == "2026-05-04"


def test_good_friday_2026() -> None:
    # Easter Sunday 2026 = April 5; Good Friday = April 3
    assert date(2026, 4, 3) in us_market_holidays(2026)
    assert is_trading_day("2026-04-03") is False
