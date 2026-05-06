"""Shared test helpers for building EntryCandidate / ExitCandidate fixtures."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from shared.analytics.full_analysis import compute_full_analysis
from shared.clients.mock_market_data import MockDataClient
from shared.schemas.market import OptionContract
from shared.strategy.base import (
    EntryCandidate,
    ExitCandidate,
    RuleResult,
    RuleTrace,
    RuleType,
)
from shared.strategy.exit_signals.base import (
    ExitSignal,
    ExitSignalCategory,
    ExitSignalSeverity,
    ExitSignalTrace,
)


def _make_trace(*, fired: bool = True, score: int = 5) -> RuleTrace:
    h = RuleResult(
        name="H_test", rule_type=RuleType.HARD, passed=True, score=1, max_score=1
    )
    s = RuleResult(
        name="S_test", rule_type=RuleType.SOFT, passed=True, score=score, max_score=2
    )
    return RuleTrace(
        timestamp=datetime.now(UTC),
        ticker="NVDA",
        hard_rules=[h, h, h],
        soft_rules=[s, s, s],
        all_hard_passed=True,
        soft_score=score,
        soft_max_score=6,
        confidence_label="STRONG" if fired else "VETO",
        confidence_score=Decimal(score) / Decimal("6"),
        fired=fired,
        fire_decision_reason="all_hard_passed_soft_score_5"
        if fired
        else "no_soft_confirmation",
    )


def make_option_contract(
    *,
    symbol: str = "NVDA250620C150",
    strike: Decimal = Decimal("150"),
    delta: Decimal = Decimal("0.45"),
    open_interest: int = 5000,
    volume: int = 2000,
    bid: Decimal = Decimal("3.00"),
    ask: Decimal = Decimal("3.10"),
) -> OptionContract:
    return OptionContract(
        symbol=symbol,
        underlying="NVDA",
        underlying_spot=Decimal("145.00"),
        expiration=date.today() + timedelta(days=30),
        dte=30,
        strike=strike,
        contract_type="call",
        bid=bid,
        ask=ask,
        last=None,
        volume=volume,
        open_interest=open_interest,
        iv=Decimal("0.30"),
        delta=delta,
        gamma=Decimal("0.02"),
        theta=Decimal("-0.05"),
        vega=Decimal("0.20"),
        rho=Decimal("0.10"),
    )


async def build_long_call_candidate(*, ticker: str = "NVDA") -> EntryCandidate:
    """Build an EntryCandidate using MockDataClient bars + analytics."""
    client = MockDataClient(seed=42)
    bars = await client.get_bars(ticker, "1d", limit=300)
    fa = await compute_full_analysis(ticker, bars, "1d")
    assert fa.regime is not None
    return EntryCandidate(
        ticker=ticker,
        direction="long_call",
        strategy_name="long_options_momentum",
        rule_trace=_make_trace(fired=True),
        full_analysis=fa,
        options_analysis=None,
        regime=fa.regime,
        overrides_applied={},
        confidence="STRONG",
        sizing_multiplier=Decimal("1.0"),
        max_premium=Decimal("500"),
        shortlist=[
            make_option_contract(
                symbol=f"{ticker}250620C{150 + i}",
                strike=Decimal(str(150 + i)),
            )
            for i in range(3)
        ],
        timestamp=datetime.now(UTC),
    )


def _signal(
    name: str, severity: ExitSignalSeverity, *, triggered: bool = True
) -> ExitSignal:
    return ExitSignal(
        name=name,
        category=ExitSignalCategory.PNL,
        severity=severity,
        triggered=triggered,
        description=f"{name} fired",
    )


def build_exit_candidate(
    *,
    ticker: str = "NVDA",
    position_id: int = 1,
    urgent_signal: bool = True,
) -> ExitCandidate:
    """Build a simple ExitCandidate with a configurable URGENT signal."""
    severity = (
        ExitSignalSeverity.URGENT if urgent_signal else ExitSignalSeverity.INFO
    )
    signals = [_signal("take_profit", severity, triggered=urgent_signal)]
    trace = ExitSignalTrace(
        position_id=position_id,
        timestamp=datetime.now(UTC),
        ticker=ticker,
        contract_symbol=f"{ticker}250620C150",
        entry_price=Decimal("5.00"),
        current_price=Decimal("7.50"),
        pnl_pct=Decimal("50.0"),
        pnl_dollars=Decimal("250.0"),
        quantity=1,
        dte_remaining=20,
        signals=signals,
        auto_close_triggered=False,
        auto_close_reason=None,
        urgent_count=1 if urgent_signal else 0,
        warning_count=0,
        info_count=0 if urgent_signal else 1,
        needs_claude=urgent_signal,
    )
    return ExitCandidate(
        position_id=position_id,
        ticker=ticker,
        exit_signal_type="pnl_based",
        is_auto_close=False,
        needs_claude=urgent_signal,
        auto_close_reason=None,
        triggered_signals=["take_profit"] if urgent_signal else [],
        signal_trace=trace,
        pnl_pct=Decimal("50.0"),
        pnl_dollars=Decimal("250.0"),
        dte_remaining=20,
        timestamp=datetime.now(UTC),
    )
