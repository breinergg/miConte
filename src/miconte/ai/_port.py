"""LLMProviderPort — the domain port every adapter must implement."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from miconte.ai._models import AnalyticalInterpretationRequest, InterpretationResponse


@runtime_checkable
class LLMProviderPort(Protocol):
    """Structural protocol for interchangeable LLM adapters.

    Adapters must be stateless with respect to user identity; the caller is
    responsible for isolating requests per user before constructing the
    AnalyticalInterpretationRequest payload.
    """

    async def interpret(
        self, request: AnalyticalInterpretationRequest
    ) -> InterpretationResponse:
        """Generate a natural-language interpretation of pre-computed results.

        Must never alter the numeric values supplied in ``request``.
        Must never introduce causal language ("causó", "provocó", "es la
        razón de") — enforcement is the adapter's responsibility and is also
        validated by the caller after the call returns.
        """
        ...
