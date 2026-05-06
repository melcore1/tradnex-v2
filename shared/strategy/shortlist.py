"""DTE-bucketed options shortlist for fired candidates."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from shared.schemas.market import OptionContract, OptionsChain
from shared.strategy.settings import ShortlistParams


class DTEBucket(StrEnum):
    SHORT = "short"  # 3-6 DTE
    MID = "mid"  # 7-10
    LONG = "long"  # 11-14


def _bucket_for(dte: int) -> DTEBucket | None:
    if 3 <= dte <= 6:
        return DTEBucket.SHORT
    if 7 <= dte <= 10:
        return DTEBucket.MID
    if 11 <= dte <= 14:
        return DTEBucket.LONG
    return None


def _liquidity_score(c: OptionContract) -> int:
    return int(c.open_interest) * int(c.volume)


def build_shortlist(
    chain: OptionsChain,
    direction: Literal["long_call", "long_put"],
    params: ShortlistParams | None = None,
) -> list[OptionContract]:
    """Return up to `max_total_contracts` contracts spread across DTE buckets.

    Empty result means insufficient diversity (fewer than `min_buckets` populated)
    or no contracts cleared the delta/liquidity filters.
    """
    p = params or ShortlistParams()
    contracts = chain.calls_only() if direction == "long_call" else chain.puts_only()

    # DTE filter
    contracts = [c for c in contracts if p.min_dte <= c.dte <= p.max_dte]

    # Delta filter — puts have negative delta, so filter on abs
    delta_lo = p.delta_target_low
    delta_hi = p.delta_target_high
    contracts = [c for c in contracts if delta_lo <= abs(c.delta) <= delta_hi]

    # Liquidity filter
    contracts = [c for c in contracts if _liquidity_score(c) >= p.liquidity_score_min]

    # Bucket
    buckets: dict[DTEBucket, list[OptionContract]] = {b: [] for b in DTEBucket}
    for c in contracts:
        bucket = _bucket_for(c.dte)
        if bucket is not None:
            buckets[bucket].append(c)

    # Diversity gate
    populated = [b for b, cs in buckets.items() if cs]
    if len(populated) < p.min_buckets:
        return []

    # Take top `max_per_bucket` per bucket by liquidity score
    selected: list[OptionContract] = []
    for bucket in DTEBucket:
        bucket_contracts = sorted(
            buckets[bucket],
            key=lambda c: (-_liquidity_score(c), c.dte),
        )
        selected.extend(bucket_contracts[: p.max_per_bucket])

    # Truncate to overall cap
    if len(selected) > p.max_total_contracts:
        # When we exceed the cap, prefer higher-liquidity contracts overall
        selected = sorted(selected, key=lambda c: (-_liquidity_score(c), c.dte))
        selected = selected[: p.max_total_contracts]

    # Sort final result by DTE ascending then strike ascending
    selected.sort(key=lambda c: (c.dte, Decimal(c.strike)))
    return selected
