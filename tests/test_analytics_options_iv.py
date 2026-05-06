"""IV rank, percentile, skew, term structure, VRP tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from shared.analytics import iv_percentile, iv_rank, skew, term_structure, vrp
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
