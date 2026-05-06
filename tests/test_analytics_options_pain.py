"""Max pain and P/C ratio tests."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from shared.analytics import max_pain, pc_ratio
from shared.analytics.options import InsufficientChainError
from shared.schemas.market import OptionContract, OptionsChain


def _contract(
    *,
    strike: float,
    contract_type: str,
    open_interest: int,
    spot: float = 100.0,
    expiration: date | None = None,
    volume: int = 100,
) -> OptionContract:
    exp = expiration or (datetime.now(UTC).date() + timedelta(days=7))
    dte = (exp - datetime.now(UTC).date()).days
    return OptionContract(
        symbol=(
            f"TEST{exp:%y%m%d}"
            f"{'C' if contract_type == 'call' else 'P'}"
            f"{int(strike * 1000):08d}"
        ),
        underlying="TEST",
        underlying_spot=Decimal(str(spot)),
        expiration=exp,
        dte=dte,
        strike=Decimal(str(strike)),
        contract_type=contract_type,  # type: ignore[arg-type]
        bid=Decimal("1.00"),
        ask=Decimal("1.05"),
        last=Decimal("1.02"),
        volume=volume,
        open_interest=open_interest,
        iv=Decimal("0.30"),
        delta=Decimal("0.5") if contract_type == "call" else Decimal("-0.5"),
        gamma=Decimal("0.02"),
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


def test_max_pain_balanced_strikes() -> None:
    """Heavy OI at $100 → max pain at 100. Spot at 102 → distance ~2%."""
    contracts = [
        _contract(strike=95, contract_type="put", open_interest=200),
        _contract(strike=100, contract_type="put", open_interest=2000),
        _contract(strike=100, contract_type="call", open_interest=2000),
        _contract(strike=105, contract_type="call", open_interest=200),
    ]
    chain = _chain(contracts, spot=102)
    result = max_pain(chain)
    assert result.max_pain_strike == Decimal("100")


def test_max_pain_pinning_when_spot_close() -> None:
    contracts = [
        _contract(strike=100, contract_type="put", open_interest=2000),
        _contract(strike=100, contract_type="call", open_interest=2000),
    ]
    chain = _chain(contracts, spot=100.1)
    result = max_pain(chain)
    assert result.regime == "pinning"


def test_max_pain_far_when_spot_distant() -> None:
    contracts = [
        _contract(strike=100, contract_type="put", open_interest=2000),
        _contract(strike=100, contract_type="call", open_interest=2000),
    ]
    chain = _chain(contracts, spot=120)  # 20% away
    result = max_pain(chain)
    assert result.regime == "far_from"


def test_max_pain_empty_chain_raises() -> None:
    with pytest.raises(InsufficientChainError):
        max_pain(_chain([]))


def test_pc_ratio_bearish_when_puts_dominant() -> None:
    contracts = [
        _contract(strike=100, contract_type="call", open_interest=500, volume=200),
        _contract(strike=100, contract_type="put", open_interest=2000, volume=1000),
    ]
    chain = _chain(contracts)
    result = pc_ratio(chain)
    assert result.oi_pc_ratio > Decimal("1.2")
    assert result.regime_oi == "bearish"


def test_pc_ratio_bullish_when_calls_dominant() -> None:
    contracts = [
        _contract(strike=100, contract_type="call", open_interest=2000, volume=1500),
        _contract(strike=100, contract_type="put", open_interest=500, volume=200),
    ]
    chain = _chain(contracts)
    result = pc_ratio(chain)
    assert result.oi_pc_ratio < Decimal("0.7")
    assert result.regime_oi == "bullish"


def test_pc_ratio_neutral_when_balanced() -> None:
    contracts = [
        _contract(strike=100, contract_type="call", open_interest=1000, volume=500),
        _contract(strike=100, contract_type="put", open_interest=1000, volume=500),
    ]
    chain = _chain(contracts)
    result = pc_ratio(chain)
    assert result.regime_oi == "neutral"
