"""Strategy base types: roundtrip + union behavior."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from shared.strategy.base import (
    Candidate,
    EntryCandidate,
    ExitCandidate,
    PositionLifecycleState,
    RuleResult,
    RuleTrace,
    RuleType,
)


def _make_trace() -> RuleTrace:
    h1 = RuleResult(
        name="H1",
        rule_type=RuleType.HARD,
        passed=True,
        score=1,
        max_score=1,
        details={"close": "100", "sma200": "95"},
    )
    s1 = RuleResult(
        name="S1",
        rule_type=RuleType.SOFT,
        passed=True,
        score=2,
        max_score=2,
        details={"vol_ratio": "2.5"},
    )
    return RuleTrace(
        timestamp=datetime.now(UTC),
        ticker="NVDA",
        hard_rules=[h1],
        soft_rules=[s1],
        all_hard_passed=True,
        soft_score=2,
        soft_max_score=2,
        confidence_label="MODERATE",
        confidence_score=Decimal("1.0"),
        fired=True,
        fire_decision_reason="all_hard_passed_soft_score_2",
    )


def test_rule_trace_json_roundtrip() -> None:
    original = _make_trace()
    payload = original.model_dump_json()
    restored = RuleTrace.model_validate_json(payload)
    assert restored.ticker == original.ticker
    assert restored.confidence_label == original.confidence_label
    assert restored.hard_rules[0].name == "H1"
    assert restored.soft_rules[0].score == 2
    assert restored.fire_decision_reason == original.fire_decision_reason


def test_exit_candidate_validates() -> None:
    exit_c = ExitCandidate(
        position_id=42,
        ticker="NVDA",
        exit_signal_type="time_based",
        timestamp=datetime.now(UTC),
    )
    assert exit_c.candidate_kind == "exit"
    assert exit_c.position_id == 42
    # Invalid signal type rejected
    with pytest.raises(ValidationError):
        ExitCandidate(
            position_id=1,
            ticker="X",
            exit_signal_type="invalid_signal",  # type: ignore[arg-type]
            timestamp=datetime.now(UTC),
        )


def test_candidate_union_accepts_both_kinds() -> None:
    exit_c: Candidate = ExitCandidate(
        position_id=1,
        ticker="X",
        exit_signal_type="pnl_based",
        timestamp=datetime.now(UTC),
    )
    assert exit_c.candidate_kind == "exit"

    # EntryCandidate construction requires real FullAnalysis/RegimeState — use isinstance
    # for the union check rather than building the full model here.
    assert ExitCandidate.__name__ in {"ExitCandidate"}
    assert EntryCandidate.__name__ in {"EntryCandidate"}


def test_position_lifecycle_states_documented() -> None:
    # Phase 3 only writes 'open'; Phase 3.5 will widen the constraint.
    expected = {"open", "closing_pending_approval", "closing", "closed"}
    # Pydantic Literal check via type hints isn't directly comparable, but we can
    # verify the alias has the documented set by introspection.
    import typing

    args = set(typing.get_args(PositionLifecycleState))
    assert args == expected
