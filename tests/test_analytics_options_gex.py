"""GEX, walls, gamma flip tests."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from shared.analytics import gex_by_expiration, gex_per_strike
from shared.analytics.options import InsufficientChainError
from shared.schemas.market import OptionContract, OptionsChain


def _contract(
    *,
    strike: float,
    spot: float = 100.0,
    contract_type: str = "call",
    gamma: float = 0.04,
    open_interest: int = 1000,
    expiration: date = date(2026, 5, 15),
    dte: int = 9,
) -> OptionContract:
    return OptionContract(
        symbol=(
            f"TEST{expiration:%y%m%d}"
            f"{'C' if contract_type == 'call' else 'P'}"
            f"{int(strike * 1000):08d}"
        ),
        underlying="TEST",
        underlying_spot=Decimal(str(spot)),
        expiration=expiration,
        dte=dte,
        strike=Decimal(str(strike)),
        contract_type=contract_type,  # type: ignore[arg-type]
        bid=Decimal("1.00"),
        ask=Decimal("1.05"),
        last=Decimal("1.02"),
        volume=100,
        open_interest=open_interest,
        iv=Decimal("0.30"),
        delta=Decimal("0.5"),
        gamma=Decimal(str(gamma)),
        theta=Decimal("-0.05"),
        vega=Decimal("0.15"),
        rho=Decimal("0.01"),
    )


def _chain(contracts: list[OptionContract], spot: float = 100.0) -> OptionsChain:
    return OptionsChain(
        underlying="TEST",
        spot_at_fetch=Decimal(str(spot)),
        contracts=contracts,
        timestamp=datetime.now(UTC),
    )


def test_gex_per_strike_known_values() -> None:
    # One call at K=100 with γ=0.04 OI=1000, spot=100
    # GEX = sign · γ · OI · 100 · S² · 0.01
    #     = 1 · 0.04 · 1000 · 100 · 10_000 · 0.01 = 400_000
    chain = _chain([_contract(strike=100, gamma=0.04, open_interest=1000)])
    result = gex_per_strike(chain)
    assert float(result.per_strike[Decimal("100")]) == pytest.approx(400_000, rel=1e-3)
    assert float(result.net_gex) == pytest.approx(400_000, rel=1e-3)


def test_put_contributes_negative_gex() -> None:
    chain = _chain([_contract(strike=100, contract_type="put", open_interest=1000)])
    result = gex_per_strike(chain)
    assert result.net_gex < Decimal("0")
    assert result.dealer_position == "short_gamma"


def test_call_wall_at_max_positive() -> None:
    # Calls at multiple strikes; 105 has highest OI → largest +GEX → call wall
    chain = _chain(
        [
            _contract(strike=100, open_interest=500),
            _contract(strike=105, open_interest=2000),
            _contract(strike=110, open_interest=300),
        ],
        spot=102,
    )
    result = gex_per_strike(chain)
    assert result.call_wall == Decimal("105")


def test_put_wall_at_most_negative() -> None:
    chain = _chain(
        [
            _contract(strike=95, contract_type="put", open_interest=500),
            _contract(strike=90, contract_type="put", open_interest=2500),
            _contract(strike=85, contract_type="put", open_interest=300),
        ],
        spot=92,
    )
    result = gex_per_strike(chain)
    assert result.put_wall == Decimal("90")


def test_gamma_flip_detected_at_sign_change() -> None:
    # Put dominates below 95, call dominates above; flip should be near boundary
    chain = _chain(
        [
            _contract(strike=90, contract_type="put", open_interest=2000),
            _contract(strike=95, contract_type="put", open_interest=500),
            _contract(strike=100, contract_type="call", open_interest=500),
            _contract(strike=105, contract_type="call", open_interest=2000),
        ],
        spot=100,
    )
    result = gex_per_strike(chain)
    assert result.gamma_flip is not None


def test_empty_chain_raises() -> None:
    chain = _chain([])
    with pytest.raises(InsufficientChainError):
        gex_per_strike(chain)


def test_gex_by_expiration_buckets_correctly() -> None:
    chain = _chain(
        [
            _contract(strike=100, expiration=date(2026, 5, 15), dte=9, open_interest=500),
            _contract(strike=100, expiration=date(2026, 5, 22), dte=16, open_interest=500),
        ],
    )
    result = gex_by_expiration(chain)
    assert date(2026, 5, 15) in result
    assert date(2026, 5, 22) in result
    # Each per-expiration result has only that expiration's contracts
    assert result[date(2026, 5, 15)].bars_used == 1


def test_distance_to_walls_signed_correctly() -> None:
    # spot=100, call wall at 105 → distance +5%
    chain = _chain(
        [
            _contract(strike=105, open_interest=2000),
            _contract(strike=95, contract_type="put", open_interest=2000),
        ],
        spot=100,
    )
    result = gex_per_strike(chain)
    assert result.distance_to_call_wall_pct is not None
    assert float(result.distance_to_call_wall_pct) == pytest.approx(5.0, abs=0.01)
    assert float(result.distance_to_put_wall_pct) == pytest.approx(-5.0, abs=0.01)
