"""Phase 8.7g: option_chain tool — filtered + decorated chain for LLM picking."""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.mcp.tools.option_chain import option_chain
from shared.clients.mock_market_data import MockDataClient
from tests._api_helpers import reset_modules_for_test_db
from tests._credential_helpers import TEST_ENCRYPTION_KEY


@pytest.fixture
def db_with_env(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    return reset_modules_for_test_db(tmp_path, monkeypatch)


@pytest.fixture
def mock_client() -> MockDataClient:
    return MockDataClient(seed=42)


# ---------- filter behavior ----------


async def test_default_filters_return_sweet_spot_only(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    """Defaults (21-45 DTE, |delta| 0.20-0.80) should drop the 7/14 DTE
    expiries and the deep-ITM / deep-OTM extremes."""
    result = await option_chain("NVDA", client=mock_client)
    assert result["ticker"] == "NVDA"
    assert result["filters"]["min_dte"] == 21
    assert result["filters"]["max_dte"] == 45
    contracts = result["contracts"]
    assert len(contracts) > 0
    for c in contracts:
        assert 21 <= c["dte"] <= 45, f"contract {c['symbol']} DTE={c['dte']} out of range"
        assert 0.20 <= abs(float(c["delta"])) <= 0.80


async def test_delta_band_filter_works(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    """Narrow delta band picks only near-ATM calls."""
    result = await option_chain(
        "NVDA",
        delta_min=0.45,
        delta_max=0.55,
        client=mock_client,
    )
    for c in result["contracts"]:
        assert 0.45 <= abs(float(c["delta"])) <= 0.55


async def test_contract_type_filter(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    """`contract_type='call'` returns only calls."""
    result = await option_chain(
        "NVDA",
        contract_type="call",
        client=mock_client,
    )
    assert all(c["contract_type"] == "call" for c in result["contracts"])

    result_put = await option_chain(
        "NVDA",
        contract_type="put",
        client=mock_client,
    )
    assert all(c["contract_type"] == "put" for c in result_put["contracts"])


async def test_expiration_param_overrides_dte_bounds(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    """A specific expiry date overrides min_dte/max_dte. Mock generates
    63-DTE rows at the 7/17 expiry — outside the default 21-45 window —
    but passing expiration=<that date> should still return them."""
    # Mock spits a 63-DTE expiry (2026-07-17 from MockDataClient seed=42)
    result = await option_chain(
        "NVDA",
        expiration="2026-07-17",
        client=mock_client,
    )
    assert result["filtered_count"] > 0
    for c in result["contracts"]:
        assert c["expiration"] == "2026-07-17"
        assert c["dte"] == 63  # outside default 21-45 window


async def test_limit_caps_returned_contracts(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    """`limit` caps the returned contracts; `total_available` exposes the
    pre-limit count for caller awareness."""
    result = await option_chain(
        "NVDA",
        delta_min=0.05,    # widen filters so we have plenty to slice
        delta_max=0.95,
        min_dte=0,
        max_dte=120,
        limit=5,
        client=mock_client,
    )
    assert result["filtered_count"] == 5
    assert len(result["contracts"]) == 5
    assert result["total_available"] > 5


async def test_empty_after_filters_returns_clean_response(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    """Over-restrictive filters return empty contracts without errors."""
    result = await option_chain(
        "NVDA",
        delta_min=0.999,
        delta_max=1.0,
        client=mock_client,
    )
    assert result["filtered_count"] == 0
    assert result["contracts"] == []
    # context still present
    assert "spot" in result["context"]


# ---------- decoration ----------


async def test_decoration_per_contract_fields_present(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    """Every returned contract has the LLM-ranking decoration fields."""
    result = await option_chain("NVDA", client=mock_client)
    assert len(result["contracts"]) > 0
    sample = result["contracts"][0]
    expected_keys = {
        # Identity
        "symbol", "contract_type", "strike", "expiration", "dte",
        "dte_bucket", "expiration_type", "is_non_standard",
        # Pricing
        "bid", "ask", "mid", "last", "mark", "theoretical_value",
        "mispricing_pct", "percent_change",
        # Liquidity
        "volume", "open_interest", "bid_size", "ask_size",
        "spread_pct", "liquidity_pass",
        # Greeks
        "iv", "delta", "gamma", "theta", "vega",
        # Risk signals
        "probability_itm", "breakeven", "intrinsic_value",
        "extrinsic_value", "in_the_money", "unusual_activity_flagged",
    }
    missing = expected_keys - set(sample.keys())
    assert not missing, f"missing decoration keys: {missing}"


async def test_decoration_dte_bucket_labels(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    """DTE bucket reflects the actual DTE — sweet_spot for default,
    high_gamma for narrow, positional for wide."""
    # 21-45 DTE → sweet_spot
    sweet = await option_chain("NVDA", client=mock_client)
    assert all(c["dte_bucket"] == "sweet_spot" for c in sweet["contracts"])

    # 8-20 DTE → high_gamma (mock has 14 DTE expiry in this range)
    high_gamma = await option_chain(
        "NVDA", min_dte=8, max_dte=20, client=mock_client
    )
    assert len(high_gamma["contracts"]) > 0
    assert all(c["dte_bucket"] == "high_gamma" for c in high_gamma["contracts"])

    # 46+ DTE → positional (mock has 63 DTE)
    positional = await option_chain(
        "NVDA", min_dte=46, max_dte=120, client=mock_client
    )
    assert len(positional["contracts"]) > 0
    assert all(c["dte_bucket"] == "positional" for c in positional["contracts"])


async def test_decoration_probability_itm_matches_abs_delta(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    """probability_itm should equal |delta| (industry-standard
    approximation). LLM uses it without needing to do its own abs()."""
    result = await option_chain("NVDA", client=mock_client)
    for c in result["contracts"]:
        delta = abs(float(c["delta"]))
        assert c["probability_itm"] == pytest.approx(delta, abs=0.0001)


async def test_decoration_mispricing_pct_signed_and_computed(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    """When theoretical_value is present, mispricing_pct is computed and
    signed (negative when market mid < theoretical, positive when >)."""
    result = await option_chain("NVDA", client=mock_client)
    saw_signed = False
    for c in result["contracts"]:
        if c["theoretical_value"] is None or c["mispricing_pct"] is None:
            continue
        theo = Decimal(c["theoretical_value"])
        mid = Decimal(c["mid"])
        if theo == 0:
            continue
        expected = float(((mid - theo) / theo) * Decimal("100"))
        # Round both to 2 decimal places for comparison (we round in formatter)
        assert c["mispricing_pct"] == pytest.approx(expected, abs=0.05)
        if c["mispricing_pct"] != 0:
            saw_signed = True
    # Mock generates noise so we expect at least some non-zero mispricings.
    assert saw_signed


async def test_context_block_populated(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    """The chain-wide context block has the regime + IV environment data
    the LLM needs to decide whether to buy or sell premium."""
    result = await option_chain("NVDA", client=mock_client)
    ctx = result["context"]
    assert ctx["spot"] is not None
    # Mock seeds IV history so iv_rank may or may not populate depending on
    # the daily_iv_snapshots table state; either way the key must exist.
    assert "iv_rank" in ctx
    assert "iv_percentile" in ctx
    assert "gex_regime" in ctx
    # GEX regime is always one of the enum literals (never raw None for a
    # chain with contracts).
    assert ctx["gex_regime"] in {
        "positive_gamma", "negative_gamma", "flip_zone"
    }


# ---------- validation ----------


async def test_invalid_limit_raises(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    with pytest.raises(ValueError, match="limit must be between"):
        await option_chain("NVDA", limit=0, client=mock_client)
    with pytest.raises(ValueError, match="limit must be between"):
        await option_chain("NVDA", limit=999, client=mock_client)


async def test_invalid_delta_band_raises(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    with pytest.raises(ValueError, match="delta_min/delta_max"):
        await option_chain(
            "NVDA", delta_min=0.5, delta_max=0.2, client=mock_client
        )
    with pytest.raises(ValueError, match="delta_min/delta_max"):
        await option_chain(
            "NVDA", delta_min=-0.1, delta_max=0.5, client=mock_client
        )


async def test_invalid_expiration_raises(
    db_with_env: object, mock_client: MockDataClient
) -> None:
    with pytest.raises(ValueError, match="ISO date"):
        await option_chain(
            "NVDA", expiration="not-a-date", client=mock_client
        )
