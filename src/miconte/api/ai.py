"""AI interpretation API router for miConte (Phase 9).

Endpoints:
  POST /api/v1/channels/{channel_id}/ai/interpret

The endpoint accepts pre-serialized analytics and recommendations (the same
data already returned by /analytics and /recommendations) and returns a
natural-language summary produced by the configured LLM adapter.

The endpoint:
  - Requires authentication (CurrentUserDep).
  - Enforces channel ownership (IDOR prevention).
  - Never sends real YouTube-derived data to the LLM when the compliance gate
    is closed (analytics_real_data_enabled=False).
  - Returns a valid response envelope even when the LLM is disabled or
    unavailable — callers must display deterministic results regardless.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from miconte.ai._chat import build_chat_messages, generate_chat_reply, serialize_context
from miconte.ai._models import LLMStatus
from miconte.ai._prompts import (
    build_chat_system_prompt,
    build_creator_system_prompt,
)
from miconte.ai._service import AIService
from miconte.api.deps import CurrentUserDep, DbSessionDep, SettingsDep
from miconte.persistence.repositories.channel_repo import ChannelRepository

router = APIRouter(prefix="/api/v1", tags=["ai"])


# ─── Dependency ───────────────────────────────────────────────────────────────

def get_ai_service(settings: SettingsDep) -> AIService:
    return AIService(settings=settings)


AIServiceDep = Annotated[AIService, Depends(get_ai_service)]


# ─── Schemas ──────────────────────────────────────────────────────────────────

class MetricInputSchema(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    label: str
    value: float | None = None
    unit: str | None = None
    n: int | None = None
    ci_95: tuple[float, float] | None = None
    limitations: list[str] = Field(default_factory=list)


class RecommendationInputSchema(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    rule_code: str
    priority: str
    description: str
    metrics_evidence: dict[str, Any] = Field(default_factory=dict)


class AIInterpretRequest(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    channel_title: str
    period_label: str
    metrics: list[MetricInputSchema] = Field(default_factory=list)
    recommendations: list[RecommendationInputSchema] = Field(default_factory=list)
    # real_data is intentionally absent: the server derives this from
    # settings.analytics_real_data_enabled — the client cannot assert
    # the origin of the data it supplies.
    # mode: "creator" produces structured 4-section output for the dashboard button.
    mode: Literal["creator", "technical"] = "creator"


class ChatMessageSchema(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChannelContextSchema(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    title: str
    period_label: str
    metrics: list[MetricInputSchema] = Field(default_factory=list)
    recommendations: list[RecommendationInputSchema] = Field(default_factory=list)


class AIChatRequest(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessageSchema] = Field(default_factory=list, max_length=20)
    channel_context: ChannelContextSchema


class AIChatResponse(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    channel_id: uuid.UUID
    reply: str | None
    ai_status: str
    degraded: bool
    note: str


class AIInterpretResponse(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    channel_id: uuid.UUID
    ai_status: str
    ai_summary: str | None
    provider: str
    degraded: bool
    note: str


# ─── Endpoint ─────────────────────────────────────────────────────────────────

@router.post(
    "/channels/{channel_id}/ai/interpret",
    response_model=AIInterpretResponse,
    summary="Generate AI interpretation of channel analytics",
)
async def interpret_channel_analytics(
    channel_id: uuid.UUID,
    body: AIInterpretRequest,
    current_user: CurrentUserDep,
    session: DbSessionDep,
    svc: AIServiceDep,
    settings: SettingsDep,
) -> AIInterpretResponse:
    """Return a natural-language interpretation of pre-computed analytics.

    Ownership is enforced: the channel must belong to the authenticated user.
    The real_data flag is derived from server-side settings — the client cannot
    declare that its payload contains real YouTube data to bypass the compliance gate.

    The endpoint always returns HTTP 200 with a valid envelope — a degraded
    or disabled LLM is reflected in ``ai_status``, never as an error status
    code.  Deterministic analytics and recommendations are unaffected.
    """
    # Ownership check: channel must belong to current_user (IDOR prevention).
    channel_repo = ChannelRepository(session)
    channel = channel_repo.get_by_id(channel_id)
    if channel is None or channel.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel '{channel_id}' not found or does not belong to this user.",
        )

    # Compliance gate — enforced at the endpoint level.
    # The body carries analytics content whose origin cannot be verified by the
    # server.  Until MICONTE_ANALYTICS_REAL_DATA_ENABLED is True (both YouTube
    # Data API derived-metrics compliance and, where required, Google OAuth app
    # verification have been obtained), no body content may reach any LLM adapter.
    if not settings.analytics_real_data_enabled:
        return AIInterpretResponse(
            channel_id=channel_id,
            ai_status=LLMStatus.unavailable.value,
            ai_summary=None,
            provider=settings.llm_provider,
            degraded=True,
            note=(
                "La interpretación de analítica por IA no está disponible. "
                "Se deben cumplir los requisitos de cumplimiento de YouTube Data API "
                "para métricas derivadas antes de enviar contenido analítico a "
                "cualquier adaptador LLM. "
                "Env var: MICONTE_ANALYTICS_REAL_DATA_ENABLED"
            ),
        )

    # Compliance gate is open: the server can vouch that derived-data use is
    # authorized.  Pass real_data=True so AIService records the correct status.
    system_prompt = build_creator_system_prompt() if body.mode == "creator" else None

    result = await svc.interpret_channel_analytics(
        channel_title=body.channel_title,
        period_label=body.period_label,
        metrics=[m.model_dump() for m in body.metrics],
        recommendations=[r.model_dump() for r in body.recommendations],
        real_data=True,
        system_prompt_override=system_prompt,
    )

    note: str
    if result.status == LLMStatus.disabled:
        note = (
            "La interpretación por IA está deshabilitada "
            "(MICONTE_LLM_PROVIDER=none). Los resultados deterministas "
            "están disponibles sin cambios."
        )
    elif result.status == LLMStatus.unavailable:
        note = (
            "El proveedor de IA no está disponible en este momento. "
            "Los resultados deterministas están disponibles sin cambios."
        )
    elif result.status == LLMStatus.error:
        note = (
            "La interpretación por IA no pudo completarse. "
            "Los resultados deterministas están disponibles sin cambios."
        )
    else:
        note = "Interpretación generada a partir de resultados deterministas precalculados."

    return AIInterpretResponse(
        channel_id=channel_id,
        ai_status=result.status.value,
        ai_summary=result.summary,
        provider=result.provider,
        degraded=result.degraded,
        note=note,
    )


# ─── Chat endpoint ────────────────────────────────────────────────────────────

@router.post(
    "/channels/{channel_id}/ai/chat",
    response_model=AIChatResponse,
    summary="Conversational AI chat with channel context",
)
async def chat_with_channel(
    channel_id: uuid.UUID,
    body: AIChatRequest,
    current_user: CurrentUserDep,
    session: DbSessionDep,
    settings: SettingsDep,
) -> AIChatResponse:
    """Free-form conversation with miConte AI, grounded in the channel's analytics.

    History is managed exclusively by the client and sent with each request;
    nothing is persisted in PostgreSQL.  A maximum of 20 prior turns is accepted.

    The endpoint always returns HTTP 200 — LLM failures are signalled through
    ``ai_status``, never as error status codes.
    """
    channel_repo = ChannelRepository(session)
    channel = channel_repo.get_by_id(channel_id)
    if channel is None or channel.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel '{channel_id}' not found or does not belong to this user.",
        )

    if not settings.analytics_real_data_enabled:
        return AIChatResponse(
            channel_id=channel_id,
            reply=None,
            ai_status=LLMStatus.unavailable.value,
            degraded=True,
            note=(
                "El chat de IA no está disponible hasta que se cumplan los requisitos "
                "de cumplimiento de YouTube Data API (MICONTE_ANALYTICS_REAL_DATA_ENABLED)."
            ),
        )

    if settings.llm_provider.lower() != "ollama":
        return AIChatResponse(
            channel_id=channel_id,
            reply=None,
            ai_status=LLMStatus.disabled.value,
            degraded=True,
            note="El proveedor LLM no es Ollama o está deshabilitado.",
        )

    ctx = body.channel_context
    context_json = serialize_context(
        metrics=[m.model_dump() for m in ctx.metrics],
        recommendations=[r.model_dump() for r in ctx.recommendations],
    )
    system_prompt = build_chat_system_prompt(
        channel_title=ctx.title,
        period_label=ctx.period_label,
        context_json=context_json,
    )
    messages = build_chat_messages(
        system_prompt=system_prompt,
        history=[h.model_dump() for h in body.history],
        user_message=body.message,
    )

    llm_status, reply = await generate_chat_reply(
        messages=messages,
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        timeout=settings.llm_timeout_seconds,
    )

    note: str
    if llm_status == LLMStatus.ok:
        note = "Respuesta generada por miConte AI basada en datos analíticos precalculados."
    elif llm_status == LLMStatus.unavailable:
        note = "El asistente no está disponible en este momento. Inténtalo de nuevo."
    else:
        note = "El asistente no pudo procesar la solicitud. Inténtalo de nuevo."

    return AIChatResponse(
        channel_id=channel_id,
        reply=reply,
        ai_status=llm_status.value,
        degraded=llm_status != LLMStatus.ok,
        note=note,
    )
