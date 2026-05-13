"""IV rank, percentile, skew, term structure, VRP tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from shared.analytics import (
    compute_options_analysis,
    iv_percentile,
    iv_rank,
    skew,
    term_structure,
    vrp,
)
from shared.analytics.volatility import GARCHResult
from shared.schemas.market import OptionContract, OptionsChain


def _seed_iv_history(conn, ticker: str, values: list[float]) -> None:
    today = datetime.now(UTC).date()
    rows = [
        (
            ticker,
            (today - timedelta(days=len(values) - 1 - i)).isoformat(),
            v,
            v * 0.97,
            v * 0.94,
            v,
            datetime.now(UTC).timestamp(),
        )
        for i, v in enumerate(values)
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO daily_iv_snapshots "
        "(ticker, date, iv_30d, iv_60d, iv_90d, atm_iv, recorded_ts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


@pytest.fixture
def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "iv_test.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


def test_iv_rank_high_when_current_at_top(db_conn) -> None:
    _seed_iv_history(db_conn, "TEST", [0.20] * 100 + [0.30] * 100 + [0.40] * 50)
    result = iv_rank("TEST", Decimal("0.40"), db_conn)
    assert result.rank is not None
    assert float(result.rank) > 90  # at top of range
    assert result.regime == "high"


def test_iv_rank_low_when_current_at_bottom(db_conn) -> None:
    _seed_iv_history(db_conn, "TEST", [0.20] * 100 + [0.30] * 100 + [0.40] * 50)
    result = iv_rank("TEST", Decimal("0.20"), db_conn)
    assert result.rank is not None
    assert float(result.rank) < 10
    assert result.regime == "low"


def test_iv_rank_returns_none_below_min_data_points(db_conn) -> None:
    _seed_iv_history(db_conn, "TEST", [0.30] * 5)
    result = iv_rank("TEST", Decimal("0.30"), db_conn, min_data_points=20)
    assert result.rank is None
    assert result.regime is None
    assert result.data_points == 5


def test_iv_percentile_intuitive(db_conn) -> None:
    _seed_iv_history(db_conn, "TEST", [0.10, 0.20, 0.30, 0.40, 0.50] * 6)  # 30 points
    result = iv_percentile("TEST", Decimal("0.30"), db_conn)
    assert result.percentile is not None
    # 30 is at the median → ~50-60% of values are <= 0.30
    assert 30 < float(result.percentile) < 80


def _build_chain_with_skew(put_iv: float, call_iv: float) -> OptionsChain:
    """Synthesize a chain with explicit 25-delta-ish IVs."""
    today = datetime.now(UTC).date() + timedelta(days=14)
    contracts = [
        OptionContract(
            symbol="TEST_C25D",
            underlying="TEST",
            underlying_spot=Decimal("100"),
            expiration=today,
            dte=14,
            strike=Decimal("105"),
            contract_type="call",
            bid=Decimal("1"),
            ask=Decimal("1.05"),
            last=Decimal("1.02"),
            volume=100,
            open_interest=500,
            iv=Decimal(str(call_iv)),
            delta=Decimal("0.25"),
            gamma=Decimal("0.02"),
            theta=Decimal("-0.02"),
            vega=Decimal("0.10"),
            rho=Decimal("0.01"),
        ),
        OptionContract(
            symbol="TEST_P25D",
            underlying="TEST",
            underlying_spot=Decimal("100"),
            expiration=today,
            dte=14,
            strike=Decimal("95"),
            contract_type="put",
            bid=Decimal("1"),
            ask=Decimal("1.05"),
            last=Decimal("1.02"),
            volume=100,
            open_interest=500,
            iv=Decimal(str(put_iv)),
            delta=Decimal("-0.25"),
            gamma=Decimal("0.02"),
            theta=Decimal("-0.02"),
            vega=Decimal("0.10"),
            rho=Decimal("-0.01"),
        ),
    ]
    return OptionsChain(
        underlying="TEST",
        spot_at_fetch=Decimal("100"),
        contracts=contracts,
        timestamp=datetime.now(UTC),
    )


def test_skew_normal_when_put_iv_higher() -> None:
    chain = _build_chain_with_skew(put_iv=0.32, call_iv=0.28)
    result = skew(chain)
    assert result.skew == Decimal("0.04")  # 0.32 - 0.28
    assert result.regime == "normal"


def test_skew_extreme_put_skew() -> None:
    chain = _build_chain_with_skew(put_iv=0.40, call_iv=0.28)
    result = skew(chain)
    assert result.regime == "extreme_put_skew"


def test_skew_inverted_when_call_iv_higher() -> None:
    chain = _build_chain_with_skew(put_iv=0.25, call_iv=0.32)
    result = skew(chain)
    assert result.regime == "inverted"


def _build_term_structure_chain(iv_by_dte: dict[int, float]) -> OptionsChain:
    today = datetime.now(UTC).date()
    contracts: list[OptionContract] = []
    for dte, iv in iv_by_dte.items():
        for ctype, delta_val in (("call", "0.5"), ("put", "-0.5")):
            contracts.append(
                OptionContract(
                    symbol=f"TEST_{ctype}_{dte}",
                    underlying="TEST",
                    underlying_spot=Decimal("100"),
                    expiration=today + timedelta(days=dte),
                    dte=dte,
                    strike=Decimal("100"),
                    contract_type=ctype,  # type: ignore[arg-type]
                    bid=Decimal("1"),
                    ask=Decimal("1.05"),
                    last=Decimal("1.02"),
                    volume=100,
                    open_interest=500,
                    iv=Decimal(str(iv)),
                    delta=Decimal(delta_val),
                    gamma=Decimal("0.02"),
                    theta=Decimal("-0.02"),
                    vega=Decimal("0.10"),
                    rho=Decimal("0.01"),
                )
            )
    return OptionsChain(
        underlying="TEST",
        spot_at_fetch=Decimal("100"),
        contracts=contracts,
        timestamp=datetime.now(UTC),
    )


def test_term_structure_contango_when_back_higher() -> None:
    chain = _build_term_structure_chain({7: 0.25, 30: 0.28, 90: 0.32})
    result = term_structure(chain)
    assert result.regime == "contango"
    assert result.slope > Decimal("0")


def test_term_structure_backwardation_when_front_higher() -> None:
    chain = _build_term_structure_chain({7: 0.40, 30: 0.30, 90: 0.25})
    result = term_structure(chain)
    assert result.regime == "backwardation"
    assert result.slope < Decimal("0")


def test_term_structure_skips_short_dte_expiries() -> None:
    """Regression for the live diagnostic: scout returned front_month_iv=3.29
    (= 329% annualized) because the 1-DTE pinning row was picked as "front".
    The fix: skip DTE <= 14 entirely when computing term structure."""
    # 1-DTE has a degenerate IV of 5.0. If it leaks into front_month_iv,
    # the slope and regime will be garbage.
    chain = _build_term_structure_chain({1: 5.0, 30: 0.30, 90: 0.35})
    result = term_structure(chain)
    # Front must be the 30-DTE row (IV 0.30), not the 1-DTE row.
    assert result.front_month_iv == Decimal("0.30")
    assert result.back_month_iv == Decimal("0.35")
    assert result.regime == "contango"


def test_term_structure_picks_nearest_strike_per_expiry() -> None:
    """When a longer expiry has wider strike spacing and doesn't contain the
    exact ATM strike, term_structure must pick the nearest strike rather than
    silently dropping the expiry."""
    today = datetime.now(UTC).date()
    contracts = [
        # 30-DTE: $100 strike present (ATM)
        OptionContract(
            symbol="TEST_call_30",
            underlying="TEST",
            underlying_spot=Decimal("100"),
            expiration=today + timedelta(days=30),
            dte=30,
            strike=Decimal("100"),
            contract_type="call",
            bid=Decimal("1"), ask=Decimal("1.05"), last=Decimal("1.02"),
            volume=100, open_interest=500,
            iv=Decimal("0.30"),
            delta=Decimal("0.5"), gamma=Decimal("0.02"),
            theta=Decimal("-0.02"), vega=Decimal("0.10"), rho=Decimal("0.01"),
        ),
        # 90-DTE: only $95 / $105 strikes (no exact ATM). Old code would skip
        # this expiry entirely, leaving term_structure with 1 point → raises.
        OptionContract(
            symbol="TEST_call_90_95",
            underlying="TEST",
            underlying_spot=Decimal("100"),
            expiration=today + timedelta(days=90),
            dte=90,
            strike=Decimal("95"),
            contract_type="call",
            bid=Decimal("1"), ask=Decimal("1.05"), last=Decimal("1.02"),
            volume=100, open_interest=500,
            iv=Decimal("0.35"),
            delta=Decimal("0.5"), gamma=Decimal("0.02"),
            theta=Decimal("-0.02"), vega=Decimal("0.10"), rho=Decimal("0.01"),
        ),
    ]
    chain = OptionsChain(
        underlying="TEST",
        spot_at_fetch=Decimal("100"),
        contracts=contracts,
        timestamp=datetime.now(UTC),
    )
    result = term_structure(chain)
    assert result.front_month_iv == Decimal("0.30")
    assert result.back_month_iv == Decimal("0.35")


def _make_garch(annualized: float) -> GARCHResult:
    return GARCHResult(
        timestamp=datetime.now(UTC),
        bars_used=200,
        annualized_vol_forecast=Decimal(str(annualized)),
        forecast_horizon=5,
        forecast_path=[Decimal(str(annualized))] * 5,
        omega=Decimal("0.01"),
        alpha=Decimal("0.05"),
        beta=Decimal("0.90"),
        persistence=Decimal("0.95"),
        half_life=Decimal("13.5"),
    )


def test_vrp_expensive_when_iv_far_above_realized() -> None:
    chain = _build_term_structure_chain({30: 0.30})
    garch = _make_garch(annualized=0.20)  # IV 0.30 - realized 0.20 = +0.10
    result = vrp(chain, garch)
    assert result.regime == "expensive"


def test_vrp_cheap_when_iv_below_realized() -> None:
    chain = _build_term_structure_chain({30: 0.20})
    garch = _make_garch(annualized=0.30)  # IV - realized = -0.10
    result = vrp(chain, garch)
    assert result.regime == "cheap"


def _atm_contract(
    strike: Decimal,
    dte: int,
    iv: Decimal,
    *,
    contract_type: str = "call",
) -> OptionContract:
    """ATM contract with sensible Greeks for a 100-spot chain."""
    is_call = contract_type == "call"
    return OptionContract(
        symbol=f"TEST_{contract_type[0].upper()}{strike}_{dte}",
        underlying="TEST",
        underlying_spot=Decimal("100"),
        expiration=datetime.now(UTC).date() + timedelta(days=dte),
        dte=dte,
        strike=strike,
        contract_type=contract_type,  # type: ignore[arg-type]
        bid=Decimal("1"),
        ask=Decimal("1.05"),
        last=Decimal("1.02"),
        volume=100,
        open_interest=500,
        iv=iv,
        delta=Decimal("0.50") if is_call else Decimal("-0.50"),
        gamma=Decimal("0.02"),
        theta=Decimal("-0.02"),
        vega=Decimal("0.10"),
        rho=Decimal("0.01") if is_call else Decimal("-0.01"),
    )


def test_compute_options_analysis_prefers_30dte_iv_over_1dte(db_conn) -> None:
    """Regression: after-hours scout pulled max_dte=14 chains where the closest
    ATM call was 1-DTE with annualized IV >>1. That broke IV rank/term_structure
    and zeroed expected_move. Fix: prefer 21-45 DTE for current_iv."""
    _seed_iv_history(db_conn, "TEST", [0.30, 0.40, 0.50, 0.60, 0.70, 0.80] * 10)
    # ATM strike = 100 (= spot). The 1-DTE row has a degenerate annualized IV
    # of 5.0 (500%); the 30-DTE row has a normal-range IV of 0.32.
    chain = OptionsChain(
        underlying="TEST",
        spot_at_fetch=Decimal("100"),
        contracts=[
            _atm_contract(Decimal("100"), 1, Decimal("5.0")),
            _atm_contract(Decimal("100"), 1, Decimal("4.8"), contract_type="put"),
            _atm_contract(Decimal("100"), 30, Decimal("0.32")),
            _atm_contract(Decimal("100"), 30, Decimal("0.30"), contract_type="put"),
        ],
        timestamp=datetime.now(UTC),
    )
    result = compute_options_analysis(chain, db_conn)
    assert result.iv_rank.current_iv == Decimal("0.32")
    # Sanity: rank should be a real value, not pegged at 100 by the 5.0 outlier.
    assert result.iv_rank.rank is not None
    assert float(result.iv_rank.rank) < 100.0


def test_compute_options_analysis_skips_zero_dte(db_conn) -> None:
    """Skips the unusable 0-DTE annualized IV in favor of the 30-DTE row."""
    _seed_iv_history(db_conn, "TEST", [0.30, 0.40, 0.50, 0.60, 0.70, 0.80] * 10)
    chain = OptionsChain(
        underlying="TEST",
        spot_at_fetch=Decimal("100"),
        contracts=[
            _atm_contract(Decimal("100"), 0, Decimal("9.9")),
            _atm_contract(Decimal("100"), 0, Decimal("9.8"), contract_type="put"),
            _atm_contract(Decimal("100"), 30, Decimal("0.35")),
            _atm_contract(Decimal("100"), 30, Decimal("0.34"), contract_type="put"),
        ],
        timestamp=datetime.now(UTC),
    )
    result = compute_options_analysis(chain, db_conn)
    assert result.iv_rank.current_iv == Decimal("0.35")


def test_compute_options_analysis_iv_rank_none_when_only_short_dte(db_conn) -> None:
    """Regression for the live diagnostic: scout NVDA on an expiry-day chain
    returned current_iv=6.36 (= 636% annualized) because the IV selector fell
    back to a 1-DTE row. With the per-expiry, DTE>14-only selector, the right
    answer here is `iv_rank=None` — emitting a 500%+ "current IV" pollutes
    iv-rank, term-structure slope, and expected-move comparisons."""
    _seed_iv_history(db_conn, "TEST", [0.30, 0.40, 0.50, 0.60, 0.70, 0.80] * 10)
    chain = OptionsChain(
        underlying="TEST",
        spot_at_fetch=Decimal("100"),
        contracts=[
            _atm_contract(Decimal("100"), 1, Decimal("5.0")),
            _atm_contract(Decimal("100"), 1, Decimal("4.9"), contract_type="put"),
            _atm_contract(Decimal("100"), 7, Decimal("1.2")),
            _atm_contract(Decimal("100"), 7, Decimal("1.1"), contract_type="put"),
        ],
        timestamp=datetime.now(UTC),
    )
    result = compute_options_analysis(chain, db_conn)
    assert result.iv_rank is None
    assert result.iv_percentile is None


def test_compute_options_analysis_picks_atm_per_expiry(db_conn) -> None:
    """Regression: previous selector used a chain-wide global ATM strike (e.g.
    $100 picked from the 1-DTE rows) and then required an exact strike match
    in 30-DTE rows. When 30-DTE only has $95/$105 strikes (wider spacing),
    the match failed and the fallback picked the 1-DTE row whose annualized
    IV is unusable. With per-expiry "nearest strike to spot," the 30-DTE
    $105 row is selected."""
    _seed_iv_history(db_conn, "TEST", [0.30, 0.40, 0.50, 0.60, 0.70, 0.80] * 10)
    chain = OptionsChain(
        underlying="TEST",
        spot_at_fetch=Decimal("100"),
        contracts=[
            # 1-DTE: spot-on $100 strike with degenerate annualized IV
            _atm_contract(Decimal("100"), 1, Decimal("5.0")),
            _atm_contract(Decimal("100"), 1, Decimal("4.9"), contract_type="put"),
            # 30-DTE: no $100 strike — only $95 and $105
            _atm_contract(Decimal("95"), 30, Decimal("0.31")),
            _atm_contract(Decimal("105"), 30, Decimal("0.33")),
        ],
        timestamp=datetime.now(UTC),
    )
    result = compute_options_analysis(chain, db_conn)
    assert result.iv_rank is not None
    # Nearest to spot $100 in the 30-DTE expiry: $95 and $105 are equidistant;
    # min() picks the first by stable ordering. Either is acceptable — the
    # important thing is the value is NOT the 1-DTE 5.0.
    assert result.iv_rank.current_iv in {Decimal("0.31"), Decimal("0.33")}
