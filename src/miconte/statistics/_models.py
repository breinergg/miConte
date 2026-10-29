"""Typed data structures for the miConte statistical engine outputs.

All types are pure Python dataclasses — no FastAPI, SQLAlchemy, network or LLM
dependencies are permitted in this module or anywhere in miconte.statistics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class MetricEnvelope:
    """Structured result for a single metric calculation, per docs/data-dictionary.md §1.

    Every computed or derived metric is wrapped in this envelope so that callers
    always receive the value together with its methodological context.
    """

    metric_key: str
    value: float | int | None
    unit: str
    source: str
    visibility: str
    period_start: date | datetime
    period_end: date | datetime
    sample_size: int
    ci_95: tuple[float, float] | None = None
    incomplete_observation_window: bool = False
    is_right_censored: bool = False
    data_suppressed: bool = False
    limitations: list[str] = field(default_factory=list)


@dataclass
class SampleStats:
    """Descriptive statistics for a numeric sample.

    When N < 10 the engine restricts itself to these observational measures and
    does not emit confidence intervals or p-values (docs/data-dictionary.md §4.1).
    """

    n: int
    mean: float | None
    median: float | None
    std: float | None
    q1: float | None
    q3: float | None
    min_val: float | None
    max_val: float | None
    limitations: list[str] = field(default_factory=list)


@dataclass
class NormalityResult:
    """Outcome of a normality test applied to a numeric sample."""

    test_name: str
    statistic: float
    p_value: float
    is_normal: bool
    n: int
    limitations: list[str] = field(default_factory=list)


@dataclass
class ComparisonResult:
    """Result of a two-group comparison (parametric or non-parametric).

    The test is selected automatically based on normality and sample size
    (docs/data-dictionary.md §4.2). Effect sizes and CIs are always included when
    computable; p-values are never interpreted as proof of causality.
    """

    test_name: str
    statistic: float
    p_value: float
    effect_size: float | None
    effect_size_name: str | None
    ci_95_effect: tuple[float, float] | None
    is_normal_a: bool | None
    is_normal_b: bool | None
    n_a: int
    n_b: int
    limitations: list[str] = field(default_factory=list)
