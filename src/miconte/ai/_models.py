"""Data-transfer objects for the AI interpretation layer."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class LLMStatus(StrEnum):
    ok = "ok"
    disabled = "disabled"
    unavailable = "unavailable"
    error = "error"


class MetricSummaryInput(BaseModel):
    """A single metric as computed by miconte.statistics, passed to the LLM."""

    label: str
    value: float | None = None
    unit: str | None = None
    n: int | None = None
    ci_95: tuple[float, float] | None = None
    limitations: list[str] = Field(default_factory=list)


class RecommendationInput(BaseModel):
    """A deterministic recommendation produced by miconte.recommendations."""

    rule_code: str
    priority: str
    description: str
    metrics_evidence: dict[str, Any] = Field(default_factory=dict)


class AnalyticalInterpretationRequest(BaseModel):
    """Immutable payload sent to the LLM adapter.

    Contains only already-computed results from miconte.statistics and
    miconte.recommendations.  The LLM never receives raw API data nor is
    asked to perform calculations.
    """

    channel_title: str
    period_label: str
    metrics: list[MetricSummaryInput] = Field(default_factory=list)
    recommendations: list[RecommendationInput] = Field(default_factory=list)
    language: str = "es"


class InterpretationResponse(BaseModel):
    """Response envelope returned by every LLM adapter."""

    status: LLMStatus
    summary: str | None = None
    provider: str = "none"
    model: str | None = None
    # True when status is not LLMStatus.ok — callers must still show deterministic results.
    degraded: bool = False
