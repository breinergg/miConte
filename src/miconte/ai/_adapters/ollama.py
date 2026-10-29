"""OllamaAdapter — connects to a local Ollama instance via HTTPX."""

from __future__ import annotations

import logging

import httpx

from miconte.ai._models import (
    AnalyticalInterpretationRequest,
    InterpretationResponse,
    LLMStatus,
)
from miconte.ai._prompts import build_system_prompt, build_user_message
from miconte.ai._validation import contains_causal_language

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:11434"
_DEFAULT_MODEL = "llama3.2"
_DEFAULT_TIMEOUT = 30.0


class OllamaAdapter:
    """Sends pre-computed analytics results to a local Ollama instance.

    Never passes raw YouTube API data to Ollama — only the already-computed
    statistical summaries produced by miconte.statistics.

    Args:
        base_url: Ollama HTTP base URL (MICONTE_OLLAMA_BASE_URL).
        model: Ollama model name (MICONTE_OLLAMA_MODEL).
        timeout: Request timeout in seconds (MICONTE_LLM_TIMEOUT_SECONDS).
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        model: str = _DEFAULT_MODEL,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    async def interpret(
        self, request: AnalyticalInterpretationRequest
    ) -> InterpretationResponse:
        system_prompt = build_system_prompt()
        user_message = build_user_message(request)

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException:
            logger.warning("Ollama request timed out after %.1fs", self._timeout)
            return InterpretationResponse(
                status=LLMStatus.unavailable,
                summary=None,
                provider="ollama",
                model=self._model,
                degraded=True,
            )
        except httpx.HTTPStatusError as exc:
            logger.warning("Ollama returned HTTP %s", exc.response.status_code)
            return InterpretationResponse(
                status=LLMStatus.unavailable,
                summary=None,
                provider="ollama",
                model=self._model,
                degraded=True,
            )
        except Exception:
            logger.exception("Unexpected error calling Ollama")
            return InterpretationResponse(
                status=LLMStatus.error,
                summary=None,
                provider="ollama",
                model=self._model,
                degraded=True,
            )

        summary = _extract_content(data)
        if summary is None:
            logger.warning("Ollama response had no message content")
            return InterpretationResponse(
                status=LLMStatus.error,
                summary=None,
                provider="ollama",
                model=self._model,
                degraded=True,
            )

        if contains_causal_language(summary):
            logger.warning("Ollama response contained causal language — discarding")
            return InterpretationResponse(
                status=LLMStatus.error,
                summary=None,
                provider="ollama",
                model=self._model,
                degraded=True,
            )

        return InterpretationResponse(
            status=LLMStatus.ok,
            summary=summary,
            provider="ollama",
            model=self._model,
            degraded=False,
        )


def _extract_content(data: dict) -> str | None:  # type: ignore[type-arg]
    try:
        return str(data["message"]["content"])
    except (KeyError, TypeError):
        return None
