"""Base types and helpers for the analytics layer.

Indicators are pure functions: bars in, IndicatorResult out. All math runs on
numpy floats internally; results are converted to Decimal at the boundary.
"""

from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal

import numpy as np
from pydantic import BaseModel, ConfigDict


class InsufficientBarsError(ValueError):
    """Raised when a caller passes fewer bars than the indicator requires."""

    def __init__(self, required: int, got: int) -> None:
        self.required = required
        self.got = got
        super().__init__(f"Need at least {required} bars, got {got}")


class GARCHFitError(RuntimeError):
    """Raised when a GARCH(1,1) fit fails to converge."""


class IndicatorResult(BaseModel):
    """Common header for all indicator result models."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    bars_used: int


def to_decimal(value: float | int, ndigits: int = 4) -> Decimal:
    """Convert a numpy/Python float to Decimal, sanitizing NaN/inf."""
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return Decimal("0")
    return Decimal(str(round(float(value), ndigits)))


def decimal_series(arr: np.ndarray, ndigits: int = 4) -> list[Decimal]:
    return [to_decimal(float(v), ndigits) for v in arr]


def true_range(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
    """Compute true range over an OHLC series. Index 0 is just high - low."""
    n = len(highs)
    tr = np.empty(n)
    tr[0] = highs[0] - lows[0]
    if n > 1:
        prev_close = closes[:-1]
        tr_high_low = highs[1:] - lows[1:]
        tr_high_pc = np.abs(highs[1:] - prev_close)
        tr_low_pc = np.abs(lows[1:] - prev_close)
        tr[1:] = np.maximum.reduce([tr_high_low, tr_high_pc, tr_low_pc])
    return tr


def wilder_smooth(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder's smoothing. Returns full-length array; pre-window indices are 0."""
    n = len(values)
    out = np.zeros(n)
    if n < period:
        return out
    out[period - 1] = values[:period].mean()
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + values[i]) / period
    return out


def ema_array(values: np.ndarray, period: int) -> np.ndarray:
    """EMA over `values`; first valid index is `period - 1`."""
    n = len(values)
    out = np.zeros(n)
    if n < period:
        return out
    alpha = 2.0 / (period + 1)
    out[period - 1] = values[:period].mean()
    for i in range(period, n):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def closes_array(bars) -> np.ndarray:  # type: ignore[no-untyped-def]
    return np.array([float(b.close) for b in bars], dtype=np.float64)


def highs_array(bars) -> np.ndarray:  # type: ignore[no-untyped-def]
    return np.array([float(b.high) for b in bars], dtype=np.float64)


def lows_array(bars) -> np.ndarray:  # type: ignore[no-untyped-def]
    return np.array([float(b.low) for b in bars], dtype=np.float64)


def volumes_array(bars) -> np.ndarray:  # type: ignore[no-untyped-def]
    return np.array([b.volume for b in bars], dtype=np.float64)
