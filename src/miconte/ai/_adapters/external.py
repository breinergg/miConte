"""ExternalAPIAdapter — connects to an OpenAI-compatible external LLM API."""

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

_DEFAULT_TIMEOUT = 45.0


class ExternalAPIAdapter:
    """Sends pre-computed analytics to a remote chat/completions-compatible API.

    Compatible with OpenAI, Anthropic (via base_url), and any provider that
    exposes a POST /chat/completions or equivalent endpoint.

    The API key is passed via the Authorization header and is never sent to
    Angular or stored in miconte_db.

    Args:
        base_url: Full endpoint URL (MICONTE_EXTERNAL_LLM_BASE_URL).
        api_key: Bearer token / API key (MICONTE_EXTERNAL_LLM_API_KEY).
        model: Model identifier (MICONTE_EXTERNAL_LLM_MODEL).
        timeout: Request timeout in seconds (MICONTE_LLM_TIMEOUT_SECONDS).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
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
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException:
            logger.warning("External LLM request timed out after %.1fs", self._timeout)
            return InterpretationResponse(
                status=LLMStatus.unavailable,
                summary=None,
                provider="external",
                model=self._model,
                degraded=True,
            )
        except httpx.HTTPStatusError as exc:
            logger.warning("External LLM returned HTTP %s", exc.response.status_code)
            return InterpretationResponse(
                status=LLMStatus.unavailable,
                summary=None,
                provider="external",
                model=self._model,
                degraded=True,
            )
        except Exception:
            logger.exception("Unexpected error calling external LLM")
            return InterpretationResponse(
                status=LLMStatus.error,
                summary=None,
                provider="external",
                model=self._model,
                degraded=True,
            )

        summary = _extract_openai_content(data)
        if summary is None:
            logger.warning("External LLM response had no message content")
            return InterpretationResponse(
                status=LLMStatus.error,
                summary=None,
                provider="external",
                model=self._model,
                degraded=True,
            )

        if contains_causal_language(summary):
            logger.warning("External LLM response contained causal language — discarding")
            return InterpretationResponse(
                status=LLMStatus.error,
                summary=None,
                provider="external",
                model=self._model,
                degraded=True,
            )

        return InterpretationResponse(
            status=LLMStatus.ok,
            summary=summary,
            provider="external",
            model=self._model,
            degraded=False,
        )


def _extract_openai_content(data: dict) -> str | None:  # type: ignore[type-arg]
    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError):
        return None
