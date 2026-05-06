"""Expected move, UOA, premium flow tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from shared.analytics import expected_move, net_premium_flow, unusual_activity
from shared.analytics.options import InsufficientChainError
from shared.schemas.market import OptionContract, OptionsChain


def _make(strike: float, ctype: str, oi: int, vol: int, mid: float = 1.0) -> OptionContract:
    exp = datetime.now(UTC).date() + timedelta(days=7)
    return OptionContract(
        symbol=f"TEST_{ctype}_{int(strike)}",
        underlying="TEST",
        underlying_spot=Decimal("100"),
        expiration=exp,
        dte=7,
        strike=Decimal(str(strike)),
        contract_type=ctype,  # type: ignore[arg-type]
        bid=Decimal(str(round(mid - 0.05, 2))),
        ask=Decimal(str(round(mid + 0.05, 2))),
        last=Decimal(str(mid)),
        volume=vol,
        open_interest=oi,
        iv=Decimal("0.30"),
        delta=Decimal("0.5") if ctype == "call" else Decimal("-0.5"),
        gamma=Decimal("0.02"),
        theta=Decimal("-0.02"),
        vega=Decimal("0.10"),
        rho=Decimal("0.01"),
    )


def _chain(contracts: list[OptionContract], spot: float = 100.0) -> OptionsChain:
    return OptionsChain(
        underlying="TEST",
        spot_at_fetch=Decimal(str(spot)),
        contracts=contracts,
        timestamp=datetime.now(UTC),
    )


def test_expected_move_from_atm_straddle() -> None:
    chain = _chain([_make(100, "call", 500, 100, mid=2.5), _make(100, "put", 500, 100, mid=2.0)])
    result = expected_move(chain)
    assert result.atm_strike == Decimal("100")
    # straddle = mid_call + mid_put = ~2.5 + ~2.0 = ~4.5
    assert Decimal("4.0") < result.straddle_price < Decimal("5.0")
    assert result.upside_target > Decimal("100")
    assert result.downside_target < Decimal("100")


def test_expected_move_no_atm_call_raises() -> None:
    chain = _chain([_make(100, "put", 500, 100)])
    with pytest.raises(InsufficientChainError):
        expected_move(chain)


def test_unusual_activity_flags_high_vol_oi_ratio() -> None:
    # OI 100, volume 500 → ratio 5.0 (above default 2.0 threshold)
    chain = _chain(
        [
            _make(100, "call", oi=100, vol=500, mid=1.0),
            _make(100, "put", oi=1000, vol=200, mid=1.0),  # ratio 0.2 → not flagged
        ]
    )
    result = unusual_activity(chain)
    assert len(result.flagged_contracts) == 1
    assert result.flagged_contracts[0].classification == "bullish"
    assert result.flagged_contracts[0].ratio == Decimal("5")


def test_unusual_activity_skips_zero_oi() -> None:
    chain = _chain([_make(100, "call", oi=0, vol=1000)])
    result = unusual_activity(chain)
    assert result.flagged_contracts == []


def test_unusual_activity_direction_bullish_when_call_premium_dominates() -> None:
    chain = _chain(
        [
            _make(100, "call", oi=100, vol=2000, mid=2.0),  # huge bullish flow
            _make(100, "put", oi=100, vol=300, mid=1.0),  # smaller flow
        ]
    )
    result = unusual_activity(chain)
    assert result.bullish_flow_dollars > result.bearish_flow_dollars
    assert result.net_flow_direction == "bullish"


def test_net_premium_flow_bullish_when_call_volume_dominates() -> None:
    chain = _chain(
        [
            _make(100, "call", oi=500, vol=10000, mid=2.0),  # big call premium
            _make(100, "put", oi=500, vol=500, mid=1.0),  # small put premium
        ]
    )
    result = net_premium_flow(chain)
    assert result.total_call_premium > result.total_put_premium
    assert result.direction == "bullish"


def test_net_premium_flow_bearish_when_put_volume_dominates() -> None:
    chain = _chain(
        [
            _make(100, "call", oi=500, vol=500, mid=1.0),
            _make(100, "put", oi=500, vol=10000, mid=2.0),
        ]
    )
    result = net_premium_flow(chain)
    assert result.direction == "bearish"


def test_net_premium_flow_empty_chain_raises() -> None:
    with pytest.raises(InsufficientChainError):
        net_premium_flow(_chain([]))
