from datetime import UTC, date, datetime
from decimal import Decimal

from shared.schemas.market import (
    OptionContract,
    OptionsChain,
    Quote,
)


def _make_quote(
    spot: str = "100.00",
    prev: str = "98.00",
    volume: int = 1_500_000,
    avg: int = 1_000_000,
) -> Quote:
    return Quote(
        ticker="TEST",
        spot=Decimal(spot),
        bid=Decimal(spot),
        ask=Decimal(spot),
        bid_size=10,
        ask_size=10,
        day_open=Decimal(prev),
        day_high=Decimal(spot),
        day_low=Decimal(prev),
        prev_close=Decimal(prev),
        volume=volume,
        avg_volume_30d=avg,
        is_market_open=True,
        timestamp=datetime.now(UTC),
    )


def _make_contract(
    *,
    contract_type: str = "call",
    strike: str = "100.00",
    spot: str = "100.00",
    bid: str = "2.00",
    ask: str = "2.10",
    dte: int = 7,
    last: str | None = "2.05",
) -> OptionContract:
    return OptionContract(
        symbol="TEST260515C00100000",
        underlying="TEST",
        underlying_spot=Decimal(spot),
        expiration=date(2026, 5, 15),
        dte=dte,
        strike=Decimal(strike),
        contract_type=contract_type,  # type: ignore[arg-type]
        bid=Decimal(bid),
        ask=Decimal(ask),
        last=Decimal(last) if last is not None else None,
        volume=100,
        open_interest=500,
        iv=Decimal("0.30"),
        delta=Decimal("0.50"),
        gamma=Decimal("0.04"),
        theta=Decimal("-0.05"),
        vega=Decimal("0.15"),
        rho=Decimal("0.01"),
    )


def test_quote_day_change_pct() -> None:
    q = _make_quote(spot="110.00", prev="100.00")
    assert q.day_change == Decimal("10.00")
    assert q.day_change_pct == Decimal("10")


def test_quote_volume_vs_avg() -> None:
    q = _make_quote(volume=1_500_000, avg=1_000_000)
    assert q.volume_vs_avg == Decimal("1.5")


def test_quote_zero_prev_close_safe() -> None:
    q = _make_quote(spot="100", prev="0")
    assert q.day_change_pct == Decimal("0")


def test_quote_decimal_precision_preserved() -> None:
    q = _make_quote(spot="100.123456789", prev="100.123456788")
    # Decimal arithmetic preserves precision
    assert q.day_change == Decimal("0.000000001")


def test_contract_mid_correct() -> None:
    c = _make_contract(bid="2.00", ask="2.20")
    assert c.mid == Decimal("2.10")


def test_contract_intrinsic_call_itm() -> None:
    c = _make_contract(contract_type="call", strike="100", spot="110")
    assert c.intrinsic_value == Decimal("10")


def test_contract_intrinsic_call_otm() -> None:
    c = _make_contract(contract_type="call", strike="110", spot="100")
    assert c.intrinsic_value == Decimal("0")


def test_contract_intrinsic_put_itm() -> None:
    c = _make_contract(contract_type="put", strike="110", spot="100")
    assert c.intrinsic_value == Decimal("10")


def test_contract_intrinsic_put_otm() -> None:
    c = _make_contract(contract_type="put", strike="100", spot="110")
    assert c.intrinsic_value == Decimal("0")


def test_contract_extrinsic_atm() -> None:
    # ATM call: intrinsic is 0, extrinsic is the entire mid
    c = _make_contract(contract_type="call", strike="100", spot="100", bid="2.00", ask="2.20")
    assert c.intrinsic_value == Decimal("0")
    assert c.extrinsic_value == Decimal("2.10")


def test_contract_extrinsic_deep_itm() -> None:
    # Deep ITM call worth $10 intrinsic, mid $10.10 → extrinsic $0.10
    c = _make_contract(contract_type="call", strike="100", spot="110", bid="10.00", ask="10.20")
    assert c.intrinsic_value == Decimal("10")
    assert c.extrinsic_value == Decimal("0.10")


def test_contract_spread_pct() -> None:
    c = _make_contract(bid="2.00", ask="2.20")
    # spread = 0.20, mid = 2.10 → ~9.52%
    assert c.spread_pct > Decimal("9")
    assert c.spread_pct < Decimal("10")


def _chain_with_contracts(contracts: list[OptionContract]) -> OptionsChain:
    return OptionsChain(
        underlying="TEST",
        spot_at_fetch=Decimal("100"),
        contracts=contracts,
        timestamp=datetime.now(UTC),
    )


def test_chain_for_expiration_filters() -> None:
    c1 = _make_contract(strike="100")
    chain = _chain_with_contracts([c1])
    assert chain.for_expiration(date(2026, 5, 15)) == [c1]
    assert chain.for_expiration(date(2026, 6, 19)) == []


def test_chain_for_dte_range() -> None:
    c_short = OptionContract(**{**_make_contract().model_dump(), "dte": 3})
    c_long = OptionContract(**{**_make_contract().model_dump(), "dte": 30})
    chain = _chain_with_contracts([c_short, c_long])
    assert chain.for_dte_range(0, 7) == [c_short]
    assert chain.for_dte_range(20, 60) == [c_long]


def test_chain_calls_puts_split() -> None:
    call = _make_contract(contract_type="call")
    put = _make_contract(contract_type="put")
    chain = _chain_with_contracts([call, put])
    assert chain.calls_only() == [call]
    assert chain.puts_only() == [put]


def test_chain_for_strike_range() -> None:
    c95 = _make_contract(strike="95")
    c100 = _make_contract(strike="100")
    c105 = _make_contract(strike="105")
    chain = _chain_with_contracts([c95, c100, c105])
    result = chain.for_strike_range(Decimal("96"), Decimal("104"))
    assert result == [c100]


def test_chain_expirations_unique_sorted() -> None:
    c_may = OptionContract(**{**_make_contract().model_dump(), "expiration": date(2026, 5, 15)})
    c_jun = OptionContract(**{**_make_contract().model_dump(), "expiration": date(2026, 6, 19)})
    c_may_dup = OptionContract(**{**_make_contract().model_dump(), "expiration": date(2026, 5, 15)})
    chain = _chain_with_contracts([c_jun, c_may, c_may_dup])
    assert chain.expirations == [date(2026, 5, 15), date(2026, 6, 19)]
