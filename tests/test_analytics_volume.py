"""Volume analytics tests: VWAP, volume vs average."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from shared.analytics import InsufficientBarsError, volume_vs_avg, vwap
from shared.schemas.market import Bar


def _bars_constant(close: float, n: int, volume: int = 1_000_000) -> list[Bar]:
    return [
        Bar(
            timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=i),
            open=Decimal(str(close)),
            high=Decimal(str(close)),
            low=Decimal(str(close)),
            close=Decimal(str(close)),
            volume=volume,
        )
        for i in range(n)
    ]


def test_vwap_constant_data_equals_price() -> None:
    bars = _bars_constant(100.0, 30)
    result = vwap(bars)
    assert result.latest == Decimal("100")


def test_vwap_known_two_bar_calc() -> None:
    bars = [
        Bar(
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=1000,
        ),
        Bar(
            timestamp=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
            open=Decimal("110"),
            high=Decimal("110"),
            low=Decimal("110"),
            close=Decimal("110"),
            volume=1000,
        ),
    ]
    # typical = price (since H=L=C); VWAP = (100*1000 + 110*1000) / 2000 = 105
    result = vwap(bars)
    assert result.latest == Decimal("105")


def test_vwap_empty_bars_raises() -> None:
    with pytest.raises(InsufficientBarsError):
        vwap([])


def test_volume_vs_avg_basic() -> None:
    # 30 bars of 1M volume + today at 2M → ratio 2.0
    bars = _bars_constant(100.0, 30, volume=1_000_000)
    bars.append(
        Bar(
            timestamp=datetime(2026, 2, 1, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=2_000_000,
        )
    )
    result = volume_vs_avg(bars, period=30)
    assert result.today_volume == 2_000_000
    assert result.avg_volume == 1_000_000
    assert result.latest_ratio == Decimal("2")


def test_volume_vs_avg_insufficient_bars() -> None:
    bars = _bars_constant(100.0, 10)
    with pytest.raises(InsufficientBarsError):
        volume_vs_avg(bars, period=30)
