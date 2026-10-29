"""Recommendations engine: applies all rules to a RecommendationSignal.

Pure function, no I/O, no randomness.
"""

from __future__ import annotations

from miconte.recommendations._models import RecommendationResult, RecommendationSignal
from miconte.recommendations._rules import _ALL_RULES


def evaluate_rules(signal: RecommendationSignal) -> list[RecommendationResult]:
    """Apply every registered rule to *signal* and return all results.

    All rules are evaluated unconditionally.  Results for rules that did not
    trigger (``triggered=False``) are included so callers can audit the full
    evaluation.

    To get only triggered results:
        triggered = [r for r in evaluate_rules(signal) if r.triggered]
    """
    return [rule(signal) for rule in _ALL_RULES]
