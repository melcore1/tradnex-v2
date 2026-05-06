"""0DTE analysis tests."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from shared.analytics import zero_dte_analysis
from shared.schemas.market import OptionContract, OptionsChain


def _contract(
    *,
    expiration: date,
    contract_type: str,
    strike: float,
    open_interest: int = 1000,
    spot: float = 100.0,
) -> OptionContract:
    today = datetime.now(UTC).date()
    dte = max((expiration - today).days, 0)
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
        bid=Decimal("0.50"),
        ask=Decimal("0.55"),
        last=Decimal("0.52"),
        volume=100,
        open_interest=open_interest,
        iv=Decimal("0.40"),
        delta=Decimal("0.5") if contract_type == "call" else Decimal("-0.5"),
        gamma=Decimal("0.05"),
        theta=Decimal("-0.10"),
        vega=Decimal("0.05"),
        rho=Decimal("0.01"),
    )


def test_returns_none_when_no_zero_dte_expiry() -> None:
    future = datetime.now(UTC).date() + timedelta(days=14)
    chain = OptionsChain(
        underlying="TEST",
        spot_at_fetch=Decimal("100"),
        contracts=[
            _contract(expiration=future, contract_type="call", strike=100),
            _contract(expiration=future, contract_type="put", strike=100),
        ],
        timestamp=datetime.now(UTC),
    )
    assert zero_dte_analysis(chain) is None


def test_present_when_today_is_expiration() -> None:
    today = datetime.now(UTC).date()
    next_week = today + timedelta(days=7)
    contracts = [
        # 0DTE
        _contract(expiration=today, contract_type="call", strike=100, open_interest=2000),
        _contract(expiration=today, contract_type="put", strike=100, open_interest=2000),
        # week-out so gex denominator isn't dominated by today
        _contract(expiration=next_week, contract_type="call", strike=100, open_interest=500),
        _contract(expiration=next_week, contract_type="put", strike=100, open_interest=500),
    ]
    chain = OptionsChain(
        underlying="TEST",
        spot_at_fetch=Decimal("100.05"),  # very close to ATM 100
        contracts=contracts,
        timestamp=datetime.now(UTC),
    )
    result = zero_dte_analysis(chain)
    assert result is not None
    assert result.expiration == today
    assert result.pin_risk in ("high", "moderate")
    assert result.expected_move > 0
    assert len(result.key_strikes) <= 3


def test_pin_risk_low_when_spot_far_from_max_pain() -> None:
    today = datetime.now(UTC).date()
    contracts = [
        _contract(expiration=today, contract_type="call", strike=100, open_interest=2000),
        _contract(expiration=today, contract_type="put", strike=100, open_interest=2000),
    ]
    chain = OptionsChain(
        underlying="TEST",
        spot_at_fetch=Decimal("110"),  # 10% from max pain at 100
        contracts=contracts,
        timestamp=datetime.now(UTC),
    )
    result = zero_dte_analysis(chain)
    assert result is not None
    assert result.pin_risk == "low"
