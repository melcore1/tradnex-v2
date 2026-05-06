"""Gap detection tests."""

from datetime import UTC, datetime
from decimal import Decimal

from shared.analytics import detect_gap
from shared.schemas.market import Quote


def _quote(spot: float, prev_close: float) -> Quote:
    return Quote(
        ticker="TEST",
        spot=Decimal(str(spot)),
        bid=Decimal(str(spot)),
        ask=Decimal(str(spot)),
        bid_size=10,
        ask_size=10,
        day_open=Decimal(str(spot)),
        day_high=Decimal(str(spot)),
        day_low=Decimal(str(spot)),
        prev_close=Decimal(str(prev_close)),
        volume=1_000_000,
        avg_volume_30d=1_000_000,
        is_market_open=True,
        timestamp=datetime.now(UTC),
    )


def test_no_severity_below_half_pct() -> None:
    g = detect_gap(_quote(spot=100.3, prev_close=100.0))
    assert g.severity == "none"


def test_minor_severity() -> None:
    g = detect_gap(_quote(spot=101.0, prev_close=100.0))
    assert g.severity == "minor"


def test_moderate_severity() -> None:
    g = detect_gap(_quote(spot=102.0, prev_close=100.0))
    assert g.severity == "moderate"


def test_severe_severity() -> None:
    g = detect_gap(_quote(spot=104.0, prev_close=100.0))
    assert g.severity == "severe"


def test_extreme_severity() -> None:
    g = detect_gap(_quote(spot=107.0, prev_close=100.0))
    assert g.severity == "extreme"


def test_direction_up_vs_down() -> None:
    up = detect_gap(_quote(spot=102.0, prev_close=100.0))
    down = detect_gap(_quote(spot=98.0, prev_close=100.0))
    assert up.direction == "up"
    assert down.direction == "down"


def test_warrants_alert_thresholds() -> None:
    none_q = detect_gap(_quote(spot=100.1, prev_close=100.0))
    minor_q = detect_gap(_quote(spot=101.0, prev_close=100.0))
    severe_q = detect_gap(_quote(spot=104.0, prev_close=100.0))
    assert none_q.warrants_alert is False
    assert minor_q.warrants_alert is False
    assert severe_q.warrants_alert is True
