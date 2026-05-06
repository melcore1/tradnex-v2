"""Strategy package: rule-based entry/exit decision logic."""

from shared.strategy.base import (
    Candidate,
    ConfidenceLabel,
    EntryCandidate,
    EntryDirection,
    ExitCandidate,
    ExitSignalType,
    PositionLifecycleState,
    RuleResult,
    RuleTrace,
    RuleType,
    Strategy,
)
from shared.strategy.exit_evaluator import evaluate_position_for_exit
from shared.strategy.exit_settings import ExitSettings
from shared.strategy.exit_signals import (
    ExitSignal,
    ExitSignalCategory,
    ExitSignalSeverity,
    ExitSignalTrace,
)
from shared.strategy.long_options_momentum import LongOptionsMomentum
from shared.strategy.settings import (
    MarketWindow,
    ShortlistParams,
    StrategySettings,
)
from shared.strategy.shortlist import DTEBucket, build_shortlist
from shared.strategy.sizing import compute_position_size

__all__ = [
    "Candidate",
    "ConfidenceLabel",
    "DTEBucket",
    "EntryCandidate",
    "EntryDirection",
    "ExitCandidate",
    "ExitSettings",
    "ExitSignal",
    "ExitSignalCategory",
    "ExitSignalSeverity",
    "ExitSignalTrace",
    "ExitSignalType",
    "LongOptionsMomentum",
    "MarketWindow",
    "PositionLifecycleState",
    "RuleResult",
    "RuleTrace",
    "RuleType",
    "ShortlistParams",
    "Strategy",
    "StrategySettings",
    "build_shortlist",
    "compute_position_size",
    "evaluate_position_for_exit",
]
