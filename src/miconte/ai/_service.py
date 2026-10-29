"""AIService — application service that wraps the LLM port.

Responsibilities:
  - Enforce the analytics compliance gate: real YouTube-derived metrics must
    not be sent to any LLM (local or remote) while the compliance flag is off.
  - Build an AnalyticalInterpretationRequest from pre-computed analytics and
    recommendation objects produced by AnalyticsService.
  - Call the configured LLM adapter and return an InterpretationResponse.
  - Guarantee graceful degradation: if the adapter raises any exception, the
    caller still receives a valid InterpretationResponse with status=error.

This service has NO dependency on miconte.statistics or the PostgreSQL session.
It only receives data that has already been computed and serialized.
"""

from __future__ import annotations

import logging
from typing import Any

from miconte.ai._models import (
    AnalyticalInterpretationRequest,
    InterpretationResponse,
    LLMStatus,
    MetricSummaryInput,
    RecommendationInput,
)
from miconte.ai._port import LLMProviderPort
from miconte.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class AIService:
    """Interprets pre-computed analytics results via the configured LLM adapter.

    Args:
        provider: An LLMProviderPort adapter (injected, defaults to factory result).
        settings: Application settings (injected for testability).
    """

    def __init__(
        self,
        provider: LLMProviderPort | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        if provider is None:
            from miconte.ai._factory import get_llm_provider
            self._provider: LLMProviderPort = get_llm_provider()
        else:
            self._provider = provider

    async def interpret_channel_analytics(
        self,
        *,
        channel_title: str,
        period_label: str,
        metrics: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
        real_data: bool = False,
    ) -> InterpretationResponse:
        """Generate a natural-language interpretation of channel analytics.

        Args:
            channel_title: Display name of the channel.
            period_label: Human-readable period string (e.g. "2026-09-27 — 2026-10-27").
            metrics: List of metric dicts matching MetricSummaryInput fields.
            recommendations: List of recommendation dicts matching RecommendationInput fields.
            real_data: True when the metrics were derived from real YouTube API data.
                       Requires analytics_real_data_enabled=True in settings.

        Returns:
            InterpretationResponse — always populated, never raises.
        """
        if real_data and not self._settings.analytics_real_data_enabled:
            # Compliance gate: never send real derived data to any LLM provider.
            logger.info(
                "AI interpretation blocked: real data requested but compliance gate is closed"
            )
            return InterpretationResponse(
                status=LLMStatus.unavailable,
                summary=None,
                provider=self._settings.llm_provider,
                model=None,
                degraded=True,
            )

        request = AnalyticalInterpretationRequest(
            channel_title=channel_title,
            period_label=period_label,
            metrics=[MetricSummaryInput(**m) for m in metrics],
            recommendations=[RecommendationInput(**r) for r in recommendations],
        )

        try:
            return await self._provider.interpret(request)
        except Exception:
            logger.exception("LLM provider raised an unexpected exception")
            return InterpretationResponse(
                status=LLMStatus.error,
                summary=None,
                provider=self._settings.llm_provider,
                model=None,
                degraded=True,
            )
