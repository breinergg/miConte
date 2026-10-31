"""miConte deterministic recommendations engine.

Pure domain module: no FastAPI, SQLAlchemy, network or LLM dependencies.
All rules are threshold-based, deterministic, and auditable.

Language contract: all rule descriptions use associative language only.
Causal claims ('causes', 'leads to', 'will result in') are prohibited.
"""

from miconte.recommendations._engine import evaluate_rules
from miconte.recommendations._models import RecommendationResult, RecommendationSignal
from miconte.recommendations._rules import (
    APV_THRESHOLD_RATIO,
    CTR_THRESHOLD_RATIO,
    ER_HIGH_OUTLIER_RATIO,
    ER_THRESHOLD_RATIO,
    MIN_BASELINE_N,
    VELOCITY_THRESHOLD,
    VIEWS_THRESHOLD_RATIO,
)

__all__ = [
    "evaluate_rules",
    "RecommendationResult",
    "RecommendationSignal",
    "MIN_BASELINE_N",
    "APV_THRESHOLD_RATIO",
    "CTR_THRESHOLD_RATIO",
    "ER_THRESHOLD_RATIO",
    "ER_HIGH_OUTLIER_RATIO",
    "VELOCITY_THRESHOLD",
    "VIEWS_THRESHOLD_RATIO",
]
