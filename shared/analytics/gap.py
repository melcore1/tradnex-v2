"""Pre-market / overnight gap detection from a single Quote."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field

from shared.schemas.market import Quote

GapSeverity = Literal["none", "minor", "moderate", "severe", "extreme"]
GapDirection = Literal["up", "down", "flat"]


class GapDetection(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    timestamp: datetime
    prev_close: Decimal
    current_price: Decimal
    gap_dollars: Decimal
    gap_pct: Decimal
    severity: GapSeverity
    direction: GapDirection

    @computed_field  # type: ignore[prop-decorator]
    @property
    def warrants_alert(self) -> bool:
        return self.severity in ("moderate", "severe", "extreme")


def detect_gap(quote: Quote) -> GapDetection:
    """Compare current spot vs previous close. Severity thresholds are hard-coded."""
    prev = quote.prev_close
    current = quote.spot
    gap_dollars = current - prev
    if prev > 0:
        gap_pct = (gap_dollars / prev * Decimal("100")).quantize(Decimal("0.0001"))
    else:
        gap_pct = Decimal("0")
    abs_pct = abs(gap_pct)

    if abs_pct < Decimal("0.5"):
        severity: GapSeverity = "none"
    elif abs_pct < Decimal("1.5"):
        severity = "minor"
    elif abs_pct < Decimal("3.0"):
        severity = "moderate"
    elif abs_pct < Decimal("5.0"):
        severity = "severe"
    else:
        severity = "extreme"

    if gap_pct > Decimal("0.05"):
        direction: GapDirection = "up"
    elif gap_pct < Decimal("-0.05"):
        direction = "down"
    else:
        direction = "flat"

    return GapDetection(
        ticker=quote.ticker,
        timestamp=datetime.now(UTC),
        prev_close=prev,
        current_price=current,
        gap_dollars=gap_dollars,
        gap_pct=gap_pct,
        severity=severity,
        direction=direction,
    )
