"""Tests for services.mcp.formatters — the JSON-shape helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from services.mcp.formatters import _first_after_dte


def test_first_after_dte_skips_short_dte_entries() -> None:
    """Regression for the live diagnostic: scout returned max_pain_front and
    expected_move_front pointing at a 1-DTE pinning row because the formatter
    used next(iter(...)). The new _first_after_dte helper walks the sorted
    dict and returns the first entry past the DTE cutoff (default 14)."""
    today = date(2026, 5, 12)
    by_exp = {
        today + timedelta(days=1): "one_dte_pinning",
        today + timedelta(days=3): "three_dte",
        today + timedelta(days=10): "ten_dte",
        today + timedelta(days=24): "twenty_four_dte",  # first past cutoff
        today + timedelta(days=52): "fifty_two_dte",
    }
    result = _first_after_dte(by_exp, today=today)
    assert result == "twenty_four_dte"


def test_first_after_dte_returns_none_when_all_short() -> None:
    """If the chain only contains short-DTE expiries, the helper returns
    None — the formatter then emits `max_pain_front: null` rather than
    fabricating a 0-DTE entry."""
    today = date(2026, 5, 12)
    by_exp = {
        today + timedelta(days=1): "one_dte",
        today + timedelta(days=7): "seven_dte",
        today + timedelta(days=14): "fourteen_dte_exact",
    }
    assert _first_after_dte(by_exp, today=today) is None


def test_first_after_dte_custom_cutoff() -> None:
    """Cutoff parameter is configurable. Default is 14 but callers can pass
    a different threshold."""
    today = date(2026, 5, 12)
    by_exp = {
        today + timedelta(days=5): "five_dte",
        today + timedelta(days=20): "twenty_dte",
    }
    # min_dte=3 picks the 5-DTE entry; min_dte=10 picks the 20-DTE entry.
    assert _first_after_dte(by_exp, min_dte=3, today=today) == "five_dte"
    assert _first_after_dte(by_exp, min_dte=10, today=today) == "twenty_dte"


def test_first_after_dte_empty_dict() -> None:
    assert _first_after_dte({}, today=date(2026, 5, 12)) is None


def test_first_after_dte_uses_today_default_when_unset() -> None:
    """If `today` isn't supplied, the helper uses datetime.now(UTC).date()."""
    today = datetime.now(UTC).date()
    by_exp = {
        today + timedelta(days=5): "skip",
        today + timedelta(days=30): "keep",
    }
    assert _first_after_dte(by_exp) == "keep"
