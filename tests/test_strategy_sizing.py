"""Position sizing math."""

from decimal import Decimal

from shared.strategy.sizing import compute_position_size


def test_strong_full_size() -> None:
    # max_premium=$500, mid=$5 → cost=$500 per contract; STRONG x1.0 → 1 contract
    assert compute_position_size("STRONG", Decimal("5"), Decimal("500")) == 1


def test_moderate_two_thirds() -> None:
    # MODERATE x0.66 = $330; $330 / ($5 * 100) = 0.66 → 0 contracts (can't afford)
    assert compute_position_size("MODERATE", Decimal("5"), Decimal("500")) == 0
    # If max_premium=$1000, MODERATE x0.66 = $660; $660 / $500 = 1.32 → 1 contract
    assert compute_position_size("MODERATE", Decimal("5"), Decimal("1000")) == 1


def test_weak_smallest_size() -> None:
    # WEAK x0.4 of $1000 = $400; $400 / ($1*100) = 4 contracts
    assert compute_position_size("WEAK", Decimal("1"), Decimal("1000")) == 4


def test_zero_or_negative_price_returns_zero() -> None:
    assert compute_position_size("STRONG", Decimal("0"), Decimal("500")) == 0
    assert compute_position_size("STRONG", Decimal("-1"), Decimal("500")) == 0


def test_zero_max_premium_returns_zero() -> None:
    assert compute_position_size("STRONG", Decimal("5"), Decimal("0")) == 0
