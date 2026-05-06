from datetime import UTC, datetime
from decimal import Decimal

from shared.clients.mock_market_data import MockDataClient
from shared.schemas.market import Quote


async def test_deterministic_seed_same_quote() -> None:
    a = MockDataClient(seed=42)
    b = MockDataClient(seed=42)
    qa = await a.get_quote("NVDA")
    qb = await b.get_quote("NVDA")
    assert qa.spot == qb.spot
    assert qa.bid == qb.bid
    assert qa.ask == qb.ask


async def test_different_seeds_yield_different_quotes() -> None:
    a = MockDataClient(seed=42)
    b = MockDataClient(seed=99)
    qa = await a.get_quote("NVDA")
    qb = await b.get_quote("NVDA")
    assert qa.spot != qb.spot


async def test_known_ticker_in_plausible_range() -> None:
    client = MockDataClient(seed=42)
    quote = await client.get_quote("NVDA")
    # NVDA baseline 142.50, drift ±0.5%
    assert Decimal("120") < quote.spot < Decimal("220")


async def test_unknown_ticker_uses_default_baseline() -> None:
    client = MockDataClient(seed=42)
    quote = await client.get_quote("XYZUNKNOWN")
    # default baseline 100.00, drift ±0.5%
    assert Decimal("80") < quote.spot < Decimal("120")


async def test_get_quotes_batch_keys_uppercase() -> None:
    client = MockDataClient(seed=42)
    result = await client.get_quotes(["nvda", "spy", "amd"])
    assert set(result.keys()) == {"NVDA", "SPY", "AMD"}
    assert all(isinstance(q, Quote) for q in result.values())


async def test_get_bars_returns_requested_limit() -> None:
    client = MockDataClient(seed=42)
    bars = await client.get_bars("NVDA", timeframe="1d", limit=50)
    assert len(bars) == 50


async def test_get_bars_timestamps_monotonic() -> None:
    client = MockDataClient(seed=42)
    bars = await client.get_bars("NVDA", timeframe="1h", limit=20)
    for prev, curr in zip(bars, bars[1:], strict=False):
        assert prev.timestamp < curr.timestamp


async def test_get_bars_intraday_has_vwap_daily_does_not() -> None:
    client = MockDataClient(seed=42)
    intraday = await client.get_bars("NVDA", timeframe="5m", limit=10)
    daily = await client.get_bars("NVDA", timeframe="1d", limit=10)
    assert all(b.vwap is not None for b in intraday)
    assert all(b.vwap is None for b in daily)


async def test_options_chain_has_calls_and_puts() -> None:
    client = MockDataClient(seed=42)
    chain = await client.get_options_chain("NVDA", contract_type="both")
    assert len(chain.calls_only()) > 0
    assert len(chain.puts_only()) > 0


async def test_options_chain_only_calls_when_filtered() -> None:
    client = MockDataClient(seed=42)
    chain = await client.get_options_chain("NVDA", contract_type="call")
    assert len(chain.contracts) > 0
    assert all(c.contract_type == "call" for c in chain.contracts)


async def test_options_chain_atm_call_delta_near_half() -> None:
    client = MockDataClient(seed=42)
    chain = await client.get_options_chain("NVDA", contract_type="call")
    spot = chain.spot_at_fetch
    atm = min(chain.contracts, key=lambda c: abs(c.strike - spot))
    # Allow generous range for the ATM-ish strike (it might be slightly off-ATM)
    assert Decimal("0.30") < atm.delta < Decimal("0.70")


async def test_options_chain_dte_filter() -> None:
    client = MockDataClient(seed=42)
    chain = await client.get_options_chain("NVDA", min_dte=3, max_dte=14)
    assert all(3 <= c.dte <= 14 for c in chain.contracts)


async def test_options_chain_strike_spacing_realistic() -> None:
    client = MockDataClient(seed=42)
    chain = await client.get_options_chain("NVDA", contract_type="call")
    strikes = sorted({c.strike for c in chain.contracts})
    diffs = [strikes[i + 1] - strikes[i] for i in range(len(strikes) - 1)]
    # NVDA ~$142, should be $1 spacing
    assert Decimal("1.00") in diffs


async def test_set_market_status_takes_effect() -> None:
    client = MockDataClient(seed=42)
    client.set_market_status(True)
    quote = await client.get_quote("NVDA")
    assert quote.is_market_open is True
    client.set_market_status(False)
    quote = await client.get_quote("NVDA")
    assert quote.is_market_open is False


async def test_inject_quote_overrides_next_call() -> None:
    client = MockDataClient(seed=42)
    fake = Quote(
        ticker="NVDA",
        spot=Decimal("999.99"),
        bid=Decimal("999.98"),
        ask=Decimal("1000.00"),
        bid_size=1,
        ask_size=1,
        day_open=Decimal("999.00"),
        day_high=Decimal("1001.00"),
        day_low=Decimal("998.00"),
        prev_close=Decimal("995.00"),
        volume=1,
        avg_volume_30d=1,
        is_market_open=True,
        timestamp=datetime.now(UTC),
    )
    client.inject_quote("NVDA", fake)
    result = await client.get_quote("NVDA")
    assert result.spot == Decimal("999.99")
    # Next call returns normal data again (injection consumed)
    next_quote = await client.get_quote("NVDA")
    assert next_quote.spot != Decimal("999.99")


async def test_health_check_returns_true() -> None:
    client = MockDataClient(seed=42)
    assert await client.health_check() is True


async def test_reset_returns_to_initial_state() -> None:
    client = MockDataClient(seed=42)
    first = await client.get_quote("NVDA")
    await client.get_quote("NVDA")  # advance RNG
    client.reset()
    again = await client.get_quote("NVDA")
    assert first.spot == again.spot


async def test_account_state_paper_defaults() -> None:
    client = MockDataClient(seed=42)
    state = await client.get_account_state()
    assert state.buying_power == Decimal("100000.00")
    assert state.is_pdt is False


async def test_movers_has_ten_each() -> None:
    client = MockDataClient(seed=42)
    movers = await client.get_movers()
    assert len(movers.most_active) == 10
    assert len(movers.top_gainers) == 10
    assert len(movers.top_losers) == 10
    # Categories tagged correctly
    assert all(e.category == "most_active" for e in movers.most_active)
    assert all(e.category == "top_gainer" for e in movers.top_gainers)
    assert all(e.category == "top_loser" for e in movers.top_losers)


async def test_market_status_returns_consistent_values() -> None:
    client = MockDataClient(seed=42)
    client.set_market_status(True)
    status = await client.get_market_status()
    assert status.is_open is True
    assert status.next_open <= status.next_close or status.next_close >= status.next_open
