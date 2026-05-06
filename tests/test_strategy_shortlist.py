"""DTE-bucketed shortlist tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from shared.schemas.market import OptionContract, OptionsChain
from shared.strategy.shortlist import build_shortlist


def _contract(
    ticker: str = "NVDA",
    *,
    strike: Decimal = Decimal("150"),
    dte: int = 5,
    contract_type: str = "call",
    delta: Decimal = Decimal("0.30"),
    oi: int = 5000,
    volume: int = 500,
    iv: Decimal = Decimal("0.35"),
) -> OptionContract:
    today = datetime.now(UTC).date()
    return OptionContract(
        symbol=f"{ticker}{(today + timedelta(days=dte)).strftime('%y%m%d')}"
        f"{'C' if contract_type == 'call' else 'P'}{int(strike * 1000):08d}",
        underlying=ticker,
        underlying_spot=Decimal("150"),
        expiration=today + timedelta(days=dte),
        dte=dte,
        strike=strike,
        contract_type=contract_type,  # type: ignore[arg-type]
        bid=Decimal("2.00"),
        ask=Decimal("2.10"),
        last=Decimal("2.05"),
        volume=volume,
        open_interest=oi,
        iv=iv,
        delta=delta,
        gamma=Decimal("0.02"),
        theta=Decimal("-0.05"),
        vega=Decimal("0.10"),
        rho=Decimal("0.01"),
    )


def _chain(contracts: list[OptionContract]) -> OptionsChain:
    return OptionsChain(
        underlying="NVDA",
        spot_at_fetch=Decimal("150"),
        contracts=contracts,
        timestamp=datetime.now(UTC),
    )


def test_single_bucket_returns_empty() -> None:
    # Three contracts all in MID bucket (dte=8) — only one bucket populated
    contracts = [
        _contract(strike=Decimal("148"), dte=8),
        _contract(strike=Decimal("150"), dte=8),
        _contract(strike=Decimal("152"), dte=8),
    ]
    out = build_shortlist(_chain(contracts), "long_call")
    assert out == []


def test_three_buckets_valid_result() -> None:
    contracts = [
        _contract(strike=Decimal("148"), dte=4),  # SHORT
        _contract(strike=Decimal("150"), dte=8),  # MID
        _contract(strike=Decimal("152"), dte=12),  # LONG
    ]
    out = build_shortlist(_chain(contracts), "long_call")
    assert len(out) == 3
    assert {c.dte for c in out} == {4, 8, 12}


def test_max_total_respected() -> None:
    # Many contracts across all 3 buckets; default max_total=5
    contracts = [
        _contract(strike=Decimal(str(150 + i)), dte=4 + (i % 3) * 4, oi=5000 - i * 10)
        for i in range(15)
    ]
    out = build_shortlist(_chain(contracts), "long_call")
    assert len(out) <= 5


def test_max_per_bucket_respected() -> None:
    # 5 contracts in SHORT bucket, 1 in MID, 1 in LONG
    contracts = [
        _contract(strike=Decimal(str(150 + i)), dte=4, oi=5000 - i * 100)
        for i in range(5)
    ]
    contracts.append(_contract(strike=Decimal("148"), dte=8))
    contracts.append(_contract(strike=Decimal("147"), dte=12))
    out = build_shortlist(_chain(contracts), "long_call")
    short_bucket = [c for c in out if 3 <= c.dte <= 6]
    assert len(short_bucket) <= 2  # default max_per_bucket=2


def test_delta_filter_excludes_far_otm() -> None:
    # Delta=0.10 (far OTM) is below default range [0.25, 0.35]
    contracts = [
        _contract(dte=4, delta=Decimal("0.10")),
        _contract(dte=8, delta=Decimal("0.10")),
        _contract(dte=12, delta=Decimal("0.10")),
    ]
    out = build_shortlist(_chain(contracts), "long_call")
    assert out == []


def test_dte_filter_excludes_outside_range() -> None:
    # DTE=2 is below min_dte=3; DTE=20 is above max_dte=14
    contracts = [
        _contract(dte=2),
        _contract(dte=4),
        _contract(dte=8),
        _contract(dte=20),
    ]
    out = build_shortlist(_chain(contracts), "long_call")
    dtes = {c.dte for c in out}
    assert 2 not in dtes
    assert 20 not in dtes


def test_liquidity_filter_excludes_thin_contracts() -> None:
    # OI*volume = 100*5 = 500, below default 1000 threshold
    contracts = [
        _contract(dte=4, oi=100, volume=5),
        _contract(dte=8, oi=100, volume=5),
        _contract(dte=12, oi=100, volume=5),
    ]
    out = build_shortlist(_chain(contracts), "long_call")
    assert out == []


def test_sorted_by_dte_ascending() -> None:
    contracts = [
        _contract(strike=Decimal("148"), dte=12),
        _contract(strike=Decimal("150"), dte=4),
        _contract(strike=Decimal("152"), dte=8),
    ]
    out = build_shortlist(_chain(contracts), "long_call")
    assert [c.dte for c in out] == sorted(c.dte for c in out)
