"""Confidence-based position sizing."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal


def compute_position_size(
    confidence: Literal["STRONG", "MODERATE", "WEAK"],
    contract_mid_price: Decimal,
    max_premium: Decimal,
    sizing_multipliers: dict[str, Decimal] | None = None,
) -> int:
    """Return the number of contracts to trade.

    multiplier = STRONG 1.0 / MODERATE 0.66 / WEAK 0.4 (by default).
    target_premium = max_premium * multiplier.
    contracts = floor(target_premium / (contract_mid_price * 100)).

    Returns 0 when contract price is non-positive or the budget can't afford
    a single contract. Never returns negative.
    """
    multipliers = sizing_multipliers or {
        "STRONG": Decimal("1.0"),
        "MODERATE": Decimal("0.66"),
        "WEAK": Decimal("0.4"),
    }
    if contract_mid_price <= 0 or max_premium <= 0:
        return 0
    multiplier = multipliers[confidence]
    target_premium = max_premium * multiplier
    contract_cost = contract_mid_price * Decimal("100")
    if contract_cost <= 0:
        return 0
    contracts = int(target_premium / contract_cost)
    return max(0, contracts)
