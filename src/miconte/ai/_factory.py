"""Factory that builds the configured LLM adapter from application settings."""

from __future__ import annotations

import logging

from miconte.ai._port import LLMProviderPort

logger = logging.getLogger(__name__)


def get_llm_provider() -> LLMProviderPort:
    """Return the LLM adapter configured via MICONTE_LLM_PROVIDER.

    Reads settings lazily so that tests can override them before the first
    call.  The result is NOT cached so that integration tests can swap the
    provider between test cases.
    """
    from miconte.ai._adapters.noop import NoOpLLMAdapter
    from miconte.core.config import get_settings

    settings = get_settings()
    provider = settings.llm_provider.lower()

    if provider == "none":
        return NoOpLLMAdapter()

    if provider == "ollama":
        from miconte.ai._adapters.ollama import OllamaAdapter
        return OllamaAdapter(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout=settings.llm_timeout_seconds,
        )

    if provider == "external":
        from miconte.ai._adapters.external import ExternalAPIAdapter
        api_key = settings.external_llm_api_key.get_secret_value()
        if not api_key:
            logger.warning(
                "MICONTE_LLM_PROVIDER=external but MICONTE_EXTERNAL_LLM_API_KEY is empty — "
                "falling back to NoOp"
            )
            return NoOpLLMAdapter()
        return ExternalAPIAdapter(
            base_url=settings.external_llm_base_url,
            api_key=api_key,
            model=settings.external_llm_model,
            timeout=settings.llm_timeout_seconds,
        )

    logger.warning("Unknown MICONTE_LLM_PROVIDER=%r — falling back to NoOp", provider)
    return NoOpLLMAdapter()
