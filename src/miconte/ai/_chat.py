"""Conversational chat helper for miConte AI.

Handles free-form conversation with channel context. Intentionally separate
from LLMProviderPort (which is for analytical interpretation) because chat
requires a variable-length messages array rather than a fixed request schema.

History is managed by the client (Angular) and sent with each request;
nothing is persisted in PostgreSQL.
"""

from __future__ import annotations

import json
import logging

import httpx

from miconte.ai._models import LLMStatus
from miconte.ai._validation import contains_causal_language

logger = logging.getLogger(__name__)


async def generate_chat_reply(
    *,
    messages: list[dict[str, str]],
    model: str,
    base_url: str,
    timeout: float,
) -> tuple[LLMStatus, str | None]:
    """Send a full conversation messages array to Ollama and return the reply.

    Args:
        messages: Complete conversation — [{"role": ..., "content": ...}, ...]
                  Must start with the system message.
        model:    Ollama model name (e.g. "qwen3.5:4b").
        base_url: Ollama HTTP base URL (e.g. "http://127.0.0.1:11434").
        timeout:  Request timeout in seconds.

    Returns:
        Tuple of (LLMStatus, reply_text | None).
        Never raises — callers receive a degraded status on any failure.
    """
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{base_url.rstrip('/')}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        logger.warning("Ollama chat timed out after %.1fs", timeout)
        return LLMStatus.unavailable, None
    except httpx.HTTPStatusError as exc:
        logger.warning("Ollama chat HTTP %s", exc.response.status_code)
        return LLMStatus.unavailable, None
    except Exception:
        logger.exception("Ollama chat unexpected error")
        return LLMStatus.error, None

    content: str = data.get("message", {}).get("content", "") or ""
    if not content.strip():
        logger.warning("Ollama chat returned empty content")
        return LLMStatus.error, None

    if contains_causal_language(content):
        logger.warning("Ollama chat response contained causal language — discarding")
        return LLMStatus.error, None

    _log_chat_perf(data, model)
    return LLMStatus.ok, content


def build_chat_messages(
    *,
    system_prompt: str,
    history: list[dict[str, str]],
    user_message: str,
) -> list[dict[str, str]]:
    """Assemble the full messages array for an Ollama /api/chat request.

    Args:
        system_prompt: Pre-built system prompt with channel context.
        history:       Previous turns — alternating assistant/user dicts,
                       oldest first, maximum 20 items enforced by the caller.
        user_message:  The current user turn.

    Returns:
        List ready to send as ``messages`` in the Ollama payload.
    """
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    return messages


def serialize_context(
    *,
    metrics: list[dict],  # type: ignore[type-arg]
    recommendations: list[dict],  # type: ignore[type-arg]
) -> str:
    """Serialize channel context to a compact JSON string for the system prompt."""
    payload = {
        "metrics": [
            {
                "label": m.get("label"),
                "value": m.get("value"),
                "unit": m.get("unit"),
                "n": m.get("n"),
                "limitations": m.get("limitations", []),
            }
            for m in metrics
        ],
        "recommendations": [
            {
                "rule_code": r.get("rule_code"),
                "priority": r.get("priority"),
                "description": r.get("description"),
            }
            for r in recommendations
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _log_chat_perf(data: dict, model: str) -> None:  # type: ignore[type-arg]
    ec: int = data.get("eval_count", 0)
    ed: int = data.get("eval_duration", 0)
    tok_s = ec / (ed / 1_000_000_000) if ed else 0.0
    logger.info("ollama chat perf model=%s tokens=%d tok/s=%.1f", model, ec, tok_s)
