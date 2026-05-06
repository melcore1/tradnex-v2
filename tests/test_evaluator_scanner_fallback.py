"""select_default_contract + scanner llm_enabled=False end-to-end tests."""

from __future__ import annotations

from decimal import Decimal

from shared.strategy.long_options_momentum import select_default_contract
from tests.fixtures.strategy_fixtures import make_option_contract


def test_picks_highest_liquidity_in_delta_range() -> None:
    a = make_option_contract(symbol="A", delta=Decimal("0.4"), open_interest=100, volume=100)
    b = make_option_contract(symbol="B", delta=Decimal("0.5"), open_interest=5000, volume=5000)
    c = make_option_contract(symbol="C", delta=Decimal("0.6"), open_interest=200, volume=200)
    pick = select_default_contract([a, b, c], (Decimal("0.30"), Decimal("0.70")))
    assert pick is not None
    assert pick.symbol == "B"


def test_empty_shortlist_returns_none() -> None:
    pick = select_default_contract([], (Decimal("0.30"), Decimal("0.70")))
    assert pick is None


def test_all_out_of_range_returns_none() -> None:
    a = make_option_contract(delta=Decimal("0.10"))
    b = make_option_contract(delta=Decimal("0.85"))
    pick = select_default_contract([a, b], (Decimal("0.30"), Decimal("0.70")))
    assert pick is None


def test_tiebreak_by_spread_when_liquidity_equal() -> None:
    """Equal liquidity → tighter spread wins."""
    tight = make_option_contract(
        symbol="TIGHT", delta=Decimal("0.5"),
        open_interest=1000, volume=1000,
        bid=Decimal("3.00"), ask=Decimal("3.05"),
    )
    wide = make_option_contract(
        symbol="WIDE", delta=Decimal("0.5"),
        open_interest=1000, volume=1000,
        bid=Decimal("3.00"), ask=Decimal("3.30"),
    )
    pick = select_default_contract([tight, wide], (Decimal("0.30"), Decimal("0.70")))
    assert pick is not None
    assert pick.symbol == "TIGHT"


def test_negative_delta_uses_abs_value() -> None:
    """Long puts have negative deltas; the helper should accept abs()."""
    put = make_option_contract(delta=Decimal("-0.45"))
    pick = select_default_contract([put], (Decimal("0.30"), Decimal("0.70")))
    assert pick is not None
