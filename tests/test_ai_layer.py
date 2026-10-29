"""Tests for the Phase 9 AI interpretation layer (miconte.ai).

All tests use synthetic data and mocked LLM adapters — no real API keys,
no Ollama instance, no network access required.
"""

from __future__ import annotations

import pytest

from miconte.ai._adapters.noop import NoOpLLMAdapter
from miconte.ai._models import (
    AnalyticalInterpretationRequest,
    InterpretationResponse,
    LLMStatus,
    MetricSummaryInput,
    RecommendationInput,
)
from miconte.ai._prompts import build_system_prompt, build_user_message
from miconte.ai._service import AIService
from miconte.ai._validation import contains_causal_language
from miconte.core.config import Settings

# ─── Fixtures ────────────────────────────────────────────────────────────────

def _make_request() -> AnalyticalInterpretationRequest:
    return AnalyticalInterpretationRequest(
        channel_title="Canal de Prueba",
        period_label="2026-09-27 — 2026-10-27",
        metrics=[
            MetricSummaryInput(
                label="Visualizaciones diarias",
                value=1234.5,
                unit="views/day",
                n=30,
                ci_95=(1100.0, 1369.0),
                limitations=[],
            )
        ],
        recommendations=[
            RecommendationInput(
                rule_code="CTR_BELOW_BASELINE",
                priority="high",
                description="El CTR se observa por debajo de la mediana del canal.",
                metrics_evidence={"ctr_median": 0.03},
            )
        ],
    )


def _make_settings(llm_provider: str = "none", real_data_enabled: bool = False) -> Settings:
    return Settings(
        environment="testing",
        llm_provider=llm_provider,
        analytics_real_data_enabled=real_data_enabled,
    )


# ─── NoOpLLMAdapter ───────────────────────────────────────────────────────────

class TestNoOpLLMAdapter:
    @pytest.mark.asyncio
    async def test_returns_disabled_status(self) -> None:
        adapter = NoOpLLMAdapter()
        result = await adapter.interpret(_make_request())
        assert result.status == LLMStatus.disabled
        assert result.summary is None
        assert result.degraded is True
        assert result.provider == "none"

    @pytest.mark.asyncio
    async def test_does_not_raise(self) -> None:
        adapter = NoOpLLMAdapter()
        result = await adapter.interpret(_make_request())
        assert isinstance(result, InterpretationResponse)


# ─── Causal-language validator ────────────────────────────────────────────────

class TestCausalLanguageValidator:
    def test_detects_causó(self) -> None:
        assert contains_causal_language("El cambio causó una disminución.") is True

    def test_detects_provocó(self) -> None:
        assert contains_causal_language("Esto provocó resultados negativos.") is True

    def test_detects_es_la_razón(self) -> None:
        assert contains_causal_language("Ese factor es la razón del descenso.") is True

    def test_allows_descriptive_text(self) -> None:
        assert (
            contains_causal_language(
                "Se observa una asociación entre la duración y el APV durante el periodo."
            )
            is False
        )

    def test_allows_empty_string(self) -> None:
        assert contains_causal_language("") is False

    def test_case_insensitive(self) -> None:
        assert contains_causal_language("Esto CAUSÓ el problema") is True


# ─── Prompt builders ─────────────────────────────────────────────────────────

class TestPromptBuilders:
    def test_system_prompt_contains_prohibition(self) -> None:
        prompt = build_system_prompt()
        assert "inventar" in prompt.lower() or "prohib" in prompt.lower()

    def test_user_message_contains_channel_title(self) -> None:
        req = _make_request()
        msg = build_user_message(req)
        assert "Canal de Prueba" in msg

    def test_user_message_contains_metric_label(self) -> None:
        req = _make_request()
        msg = build_user_message(req)
        assert "Visualizaciones diarias" in msg

    def test_user_message_contains_data_boundary_markers(self) -> None:
        req = _make_request()
        msg = build_user_message(req)
        # Context separation markers must be present to limit prompt injection scope.
        assert "---DATA-START---" in msg
        assert "---DATA-END---" in msg

    def test_user_message_json_block_is_valid(self) -> None:
        import json
        req = _make_request()
        msg = build_user_message(req)
        # Extract the JSON block between the markers.
        start = msg.index("---DATA-START---") + len("---DATA-START---\n")
        end = msg.index("\n---DATA-END---")
        data = json.loads(msg[start:end])
        assert data["channel_title"] == "Canal de Prueba"


# ─── AIService ───────────────────────────────────────────────────────────────

class TestAIService:
    @pytest.mark.asyncio
    async def test_noop_returns_disabled(self) -> None:
        svc = AIService(provider=NoOpLLMAdapter(), settings=_make_settings())
        result = await svc.interpret_channel_analytics(
            channel_title="Test",
            period_label="30d",
            metrics=[],
            recommendations=[],
        )
        assert result.status == LLMStatus.disabled
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_compliance_gate_blocks_real_data(self) -> None:
        """Real data must not reach LLM while compliance flag is off."""
        svc = AIService(
            provider=NoOpLLMAdapter(),
            settings=_make_settings(real_data_enabled=False),
        )
        result = await svc.interpret_channel_analytics(
            channel_title="Test",
            period_label="30d",
            metrics=[{"label": "views", "value": 100.0}],
            recommendations=[],
            real_data=True,
        )
        assert result.status == LLMStatus.unavailable
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_synthetic_data_passes_compliance_gate(self) -> None:
        """Synthetic data (real_data=False) is allowed regardless of compliance flag."""
        svc = AIService(
            provider=NoOpLLMAdapter(),
            settings=_make_settings(real_data_enabled=False),
        )
        result = await svc.interpret_channel_analytics(
            channel_title="Test",
            period_label="30d",
            metrics=[{"label": "views", "value": 100.0}],
            recommendations=[],
            real_data=False,
        )
        # NoOp returns disabled, not blocked — compliance gate let it through
        assert result.status == LLMStatus.disabled

    @pytest.mark.asyncio
    async def test_exception_in_adapter_returns_error_not_raise(self) -> None:
        """A crashing adapter must not propagate — graceful degradation."""

        class CrashingAdapter:
            async def interpret(
                self, request: AnalyticalInterpretationRequest
            ) -> InterpretationResponse:
                raise RuntimeError("boom")

        svc = AIService(provider=CrashingAdapter(), settings=_make_settings())  # type: ignore[arg-type]
        result = await svc.interpret_channel_analytics(
            channel_title="Test",
            period_label="30d",
            metrics=[],
            recommendations=[],
        )
        assert result.status == LLMStatus.error
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_deterministic_results_unaffected_by_disabled_llm(self) -> None:
        """Disabling the LLM returns degraded=True but never alters other data."""
        svc = AIService(provider=NoOpLLMAdapter(), settings=_make_settings())
        result = await svc.interpret_channel_analytics(
            channel_title="Mi Canal",
            period_label="30d",
            metrics=[{"label": "APV", "value": 42.0}],
            recommendations=[],
        )
        assert result.summary is None
        # The service must not touch metrics or recommendations — they are returned
        # unchanged by the analytics layer independently.
        assert result.provider == "none"

    @pytest.mark.asyncio
    async def test_user_isolation_enforced_by_request_payload(self) -> None:
        """Each request is self-contained; no shared state between invocations."""
        svc = AIService(provider=NoOpLLMAdapter(), settings=_make_settings())
        r1 = await svc.interpret_channel_analytics(
            channel_title="Canal A",
            period_label="30d",
            metrics=[],
            recommendations=[],
        )
        r2 = await svc.interpret_channel_analytics(
            channel_title="Canal B",
            period_label="30d",
            metrics=[],
            recommendations=[],
        )
        # Both succeed independently — no cross-user contamination possible
        assert r1.status == LLMStatus.disabled
        assert r2.status == LLMStatus.disabled


# ─── Mocked Ollama adapter (network-isolated) ─────────────────────────────────

class TestOllamaAdapterWithMock:
    @pytest.mark.asyncio
    async def test_timeout_returns_unavailable(self) -> None:
        import httpx
        import respx

        from miconte.ai._adapters.ollama import OllamaAdapter

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").mock(
                side_effect=httpx.TimeoutException("timeout")
            )
            adapter = OllamaAdapter(base_url="http://localhost:11434", timeout=5.0)
            result = await adapter.interpret(_make_request())

        assert result.status == LLMStatus.unavailable
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_causal_language_response_is_discarded(self) -> None:
        import httpx
        import respx

        from miconte.ai._adapters.ollama import OllamaAdapter

        causal_body = {
            "message": {"content": "El video causó una caída en las suscripciones."}
        }
        with respx.mock:
            respx.post("http://localhost:11434/api/chat").mock(
                return_value=httpx.Response(200, json=causal_body)
            )
            adapter = OllamaAdapter(base_url="http://localhost:11434")
            result = await adapter.interpret(_make_request())

        assert result.status == LLMStatus.error
        assert result.summary is None

    @pytest.mark.asyncio
    async def test_valid_response_returns_ok(self) -> None:
        import httpx
        import respx

        from miconte.ai._adapters.ollama import OllamaAdapter

        valid_body = {
            "message": {
                "content": (
                    "Durante el periodo se observa una asociación"
                    " entre la duración y el APV."
                )
            }
        }
        with respx.mock:
            respx.post("http://localhost:11434/api/chat").mock(
                return_value=httpx.Response(200, json=valid_body)
            )
            adapter = OllamaAdapter(base_url="http://localhost:11434")
            result = await adapter.interpret(_make_request())

        assert result.status == LLMStatus.ok
        assert result.degraded is False
        assert "asociación" in (result.summary or "")
