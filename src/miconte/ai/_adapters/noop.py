"""NoOpLLMAdapter — default safe adapter that returns disabled status immediately."""

from __future__ import annotations

from miconte.ai._models import (
    AnalyticalInterpretationRequest,
    InterpretationResponse,
    LLMStatus,
)


class NoOpLLMAdapter:
    """Returns LLMStatus.disabled with no network calls.

    This is the default when MICONTE_LLM_PROVIDER=none (or unset).
    """

    async def interpret(
        self, request: AnalyticalInterpretationRequest
    ) -> InterpretationResponse:
        return InterpretationResponse(
            status=LLMStatus.disabled,
            summary=None,
            provider="none",
            model=None,
            degraded=True,
        )
