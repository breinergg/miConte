"""miConte statistical engine — pure, deterministic, dependency-free.

Public API for miconte.statistics.  Import from here; do not import
from internal _* submodules directly.

Zero dependencies on FastAPI, SQLAlchemy, network calls, LLMs or MCP.
All functions receive plain Python / NumPy inputs and return typed dataclasses.
"""

from miconte.statistics._inference import (
    compare_two_groups,
    compute_ci_95,
    describe,
    test_normality,
)
from miconte.statistics._metrics import (
    compute_apv,
    compute_ctr,
    compute_engagement_rate,
    compute_nsc_1k,
    compute_public_engagement_rate,
    compute_velocity,
)
from miconte.statistics._models import (
    ComparisonResult,
    MetricEnvelope,
    NormalityResult,
    SampleStats,
)

__all__ = [
    # Data structures
    "ComparisonResult",
    "MetricEnvelope",
    "NormalityResult",
    "SampleStats",
    # Derived metrics
    "compute_apv",
    "compute_ctr",
    "compute_engagement_rate",
    "compute_nsc_1k",
    "compute_public_engagement_rate",
    "compute_velocity",
    # Inference
    "compare_two_groups",
    "compute_ci_95",
    "describe",
    "test_normality",
]
