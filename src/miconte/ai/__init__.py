"""miconte.ai — Optional AI interpretation layer (Phase 9).

All statistical computation and deterministic recommendations are produced
by miconte.statistics and miconte.recommendations before this layer is
invoked.  This module only generates natural-language summaries of results
that already exist.

Configure with:
  MICONTE_LLM_PROVIDER=none     (default, safe — no network calls)
  MICONTE_LLM_PROVIDER=ollama   (local Ollama instance)
  MICONTE_LLM_PROVIDER=external (remote API compatible with chat/completions)
"""

from miconte.ai._factory import get_llm_provider
from miconte.ai._models import (
    AnalyticalInterpretationRequest,
    InterpretationResponse,
    LLMStatus,
)
from miconte.ai._port import LLMProviderPort

__all__ = [
    "AnalyticalInterpretationRequest",
    "InterpretationResponse",
    "LLMStatus",
    "LLMProviderPort",
    "get_llm_provider",
]
