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

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from miconte.ai._models import LLMStatus
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
    result = await svc.interpret_channel_analytics(
        channel_title=body.channel_title,
        period_label=body.period_label,
        metrics=[m.model_dump() for m in body.metrics],
        recommendations=[r.model_dump() for r in body.recommendations],
        real_data=True,
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
