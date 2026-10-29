"""Analytics API router for miConte.

Endpoints:
  GET  /api/v1/channels/{channel_id}/summary
  GET  /api/v1/channels/{channel_id}/videos
  GET  /api/v1/channels/{channel_id}/analytics
  GET  /api/v1/channels/{channel_id}/recommendations
  POST /api/v1/channels/{channel_id}/analysis/run
  GET  /api/v1/videos/{video_id}/analytics

All endpoints:
  - Require authentication via CurrentUserDep (X-User-Id in dev/test).
  - Enforce channel ownership (IDOR prevention) inside AnalyticsService.
  - Return a compliance_notice field in every response.
  - Return 404 when the channel or video is not found or does not belong to the user.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from miconte.api.deps import CurrentUserDep, DbSessionDep
from miconte.services.analytics_service import (
    AnalyticsNotAvailableError,
    AnalyticsService,
    ChannelNotFoundError,
    VideoNotFoundError,
)

router = APIRouter(prefix="/api/v1", tags=["analytics"])


# ─── Pydantic v2 response schemas ────────────────────────────────────────────

class ChannelSnapshotSchema(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    captured_at: str | None
    view_count: int | None
    subscriber_count: int | None
    video_count: int | None


class ChannelSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    channel_id: uuid.UUID
    youtube_channel_id: str
    title: str
    description: str | None = None
    custom_url: str | None = None
    thumbnail_url: str | None = None
    snapshot: ChannelSnapshotSchema | None = None
    compliance_notice: str


class VideoSnapshotSchema(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    captured_at: str | None
    view_count: int | None
    like_count: int | None
    comment_count: int | None


class VideoSummarySchema(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    video_id: uuid.UUID
    youtube_video_id: str
    title: str
    published_at: str
    duration_seconds: int
    snapshot: VideoSnapshotSchema | None = None


class VideoListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    channel_id: uuid.UUID
    total_returned: int
    videos: list[VideoSummarySchema]
    compliance_notice: str


class MetricStatsSchema(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    n: int
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    min_val: float | None = None
    max_val: float | None = None
    ci_95: tuple[float, float] | None = None
    limitations: list[str] = Field(default_factory=list)


class ChannelAnalyticsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    channel_id: uuid.UUID
    period_start: str
    period_end: str
    n_days_with_data: int
    views_stats: MetricStatsSchema
    apv_stats: MetricStatsSchema
    er_stats: MetricStatsSchema
    nsc_1k_stats: MetricStatsSchema
    compliance_notice: str


class RecommendationSchema(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    recommendation_id: uuid.UUID
    rule_code: str
    title: str
    description: str
    priority: str
    metrics_evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    video_id: uuid.UUID | None = None


class RecommendationsListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    channel_id: uuid.UUID
    total_returned: int
    recommendations: list[RecommendationSchema]
    compliance_notice: str


class AnalysisRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    analysis_run_id: uuid.UUID
    n_videos_analyzed: int
    n_rules_triggered: int
    recommendations: list[RecommendationSchema]
    compliance_notice: str


class VideoMetricPointSchema(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    metric_key: str
    value: float | None = None
    unit: str
    limitations: list[str] = Field(default_factory=list)


class VideoAnalyticsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    video_id: uuid.UUID
    channel_id: uuid.UUID
    title: str
    duration_seconds: int
    period_start: str
    period_end: str
    n_days_with_data: int
    metrics: list[VideoMetricPointSchema]
    compliance_notice: str


# ─── Dependency ───────────────────────────────────────────────────────────────

def get_analytics_service(session: DbSessionDep) -> AnalyticsService:
    return AnalyticsService(session)


AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]


def _raise_unavailable(exc: Exception) -> None:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
    ) from exc


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get(
    "/channels/{channel_id}/summary",
    response_model=ChannelSummaryResponse,
    summary="Resumen del canal",
    description="Devuelve metadatos del canal y su último snapshot público.",
)
async def get_channel_summary(
    channel_id: uuid.UUID,
    current_user: CurrentUserDep,
    svc: AnalyticsServiceDep,
) -> ChannelSummaryResponse:
    try:
        data = svc.get_channel_summary(current_user.id, channel_id)
    except AnalyticsNotAvailableError as exc:
        _raise_unavailable(exc)
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    snap: ChannelSnapshotSchema | None = None
    if data.snapshot:
        snap = ChannelSnapshotSchema(
            captured_at=data.snapshot.captured_at,
            view_count=data.snapshot.view_count,
            subscriber_count=data.snapshot.subscriber_count,
            video_count=data.snapshot.video_count,
        )

    return ChannelSummaryResponse(
        channel_id=data.channel_id,
        youtube_channel_id=data.youtube_channel_id,
        title=data.title,
        description=data.description,
        custom_url=data.custom_url,
        thumbnail_url=data.thumbnail_url,
        snapshot=snap,
        compliance_notice=data.compliance_notice,
    )


@router.get(
    "/channels/{channel_id}/videos",
    response_model=VideoListResponse,
    summary="Listado de videos del canal",
    description="Devuelve una lista paginada de videos con su último snapshot público.",
)
async def list_channel_videos(
    channel_id: uuid.UUID,
    current_user: CurrentUserDep,
    svc: AnalyticsServiceDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> VideoListResponse:
    try:
        videos = svc.get_video_list(current_user.id, channel_id, limit=limit, offset=offset)
    except AnalyticsNotAvailableError as exc:
        _raise_unavailable(exc)
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    video_schemas = [
        VideoSummarySchema(
            video_id=v.video_id,
            youtube_video_id=v.youtube_video_id,
            title=v.title,
            published_at=v.published_at,
            duration_seconds=v.duration_seconds,
            snapshot=VideoSnapshotSchema(
                captured_at=v.snapshot.captured_at,
                view_count=v.snapshot.view_count,
                like_count=v.snapshot.like_count,
                comment_count=v.snapshot.comment_count,
            ) if v.snapshot else None,
        )
        for v in videos
    ]

    from miconte.services.analytics_service import COMPLIANCE_NOTICE
    return VideoListResponse(
        channel_id=channel_id,
        total_returned=len(video_schemas),
        videos=video_schemas,
        compliance_notice=COMPLIANCE_NOTICE,
    )


@router.get(
    "/channels/{channel_id}/analytics",
    response_model=ChannelAnalyticsResponse,
    summary="Analítica agregada del canal",
    description=(
        "Devuelve estadísticas descriptivas de las métricas diarias del canal "
        "para el período solicitado."
    ),
)
async def get_channel_analytics(
    channel_id: uuid.UUID,
    current_user: CurrentUserDep,
    svc: AnalyticsServiceDep,
    period_days: int = Query(default=30, ge=7, le=365),
) -> ChannelAnalyticsResponse:
    try:
        data = svc.get_channel_analytics(current_user.id, channel_id, period_days=period_days)
    except AnalyticsNotAvailableError as exc:
        _raise_unavailable(exc)
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def _stats(s: object) -> MetricStatsSchema:
        from miconte.services.analytics_service import MetricStats as MS
        assert isinstance(s, MS)
        return MetricStatsSchema(
            n=s.n,
            mean=s.mean,
            median=s.median,
            std=s.std,
            min_val=s.min_val,
            max_val=s.max_val,
            ci_95=s.ci_95,
            limitations=s.limitations,
        )

    return ChannelAnalyticsResponse(
        channel_id=data.channel_id,
        period_start=data.period_start.isoformat(),
        period_end=data.period_end.isoformat(),
        n_days_with_data=data.n_days_with_data,
        views_stats=_stats(data.views_stats),
        apv_stats=_stats(data.apv_stats),
        er_stats=_stats(data.er_stats),
        nsc_1k_stats=_stats(data.nsc_1k_stats),
        compliance_notice=data.compliance_notice,
    )


@router.get(
    "/channels/{channel_id}/recommendations",
    response_model=RecommendationsListResponse,
    summary="Recomendaciones del canal",
    description="Devuelve las recomendaciones deterministas más recientes para el canal.",
)
async def list_recommendations(
    channel_id: uuid.UUID,
    current_user: CurrentUserDep,
    svc: AnalyticsServiceDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> RecommendationsListResponse:
    try:
        recs = svc.list_recommendations(current_user.id, channel_id, limit=limit)
    except AnalyticsNotAvailableError as exc:
        _raise_unavailable(exc)
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    schemas = [
        RecommendationSchema(
            recommendation_id=r.recommendation_id,
            rule_code=r.rule_code,
            title=r.title,
            description=r.description,
            priority=r.priority,
            metrics_evidence=r.metrics_evidence,
            created_at=r.created_at,
            video_id=r.video_id,
        )
        for r in recs
    ]

    from miconte.services.analytics_service import COMPLIANCE_NOTICE
    return RecommendationsListResponse(
        channel_id=channel_id,
        total_returned=len(schemas),
        recommendations=schemas,
        compliance_notice=COMPLIANCE_NOTICE,
    )


@router.post(
    "/channels/{channel_id}/analysis/run",
    response_model=AnalysisRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ejecutar análisis y generar recomendaciones",
    description=(
        "Analiza los datos del canal de los últimos 30 días, evalúa las reglas deterministas "
        "y persiste las recomendaciones generadas."
    ),
)
async def run_analysis(
    channel_id: uuid.UUID,
    current_user: CurrentUserDep,
    svc: AnalyticsServiceDep,
) -> AnalysisRunResponse:
    try:
        data = svc.run_recommendations(current_user.id, channel_id)
    except AnalyticsNotAvailableError as exc:
        _raise_unavailable(exc)
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    rec_schemas = [
        RecommendationSchema(
            recommendation_id=r.recommendation_id,
            rule_code=r.rule_code,
            title=r.title,
            description=r.description,
            priority=r.priority,
            metrics_evidence=r.metrics_evidence,
            created_at=r.created_at,
            video_id=r.video_id,
        )
        for r in data.recommendations
    ]

    return AnalysisRunResponse(
        analysis_run_id=data.analysis_run_id,
        n_videos_analyzed=data.n_videos_analyzed,
        n_rules_triggered=data.n_rules_triggered,
        recommendations=rec_schemas,
        compliance_notice=data.compliance_notice,
    )


@router.get(
    "/videos/{video_id}/analytics",
    response_model=VideoAnalyticsResponse,
    summary="Analítica de un video individual",
    description=(
        "Devuelve métricas calculadas para un video en el período solicitado. "
        "Se requiere channel_id para verificar la propiedad del usuario (IDOR)."
    ),
)
async def get_video_analytics(
    video_id: uuid.UUID,
    current_user: CurrentUserDep,
    svc: AnalyticsServiceDep,
    channel_id: Annotated[
        uuid.UUID,
        Query(description="UUID del canal al que pertenece el video (verificación IDOR)"),
    ],
    period_days: int = Query(default=30, ge=7, le=365),
) -> VideoAnalyticsResponse:
    try:
        data = svc.get_video_analytics(
            current_user.id, channel_id, video_id, period_days=period_days
        )
    except AnalyticsNotAvailableError as exc:
        _raise_unavailable(exc)
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except VideoNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    metric_schemas = [
        VideoMetricPointSchema(
            metric_key=m.metric_key,
            value=m.value,
            unit=m.unit,
            limitations=m.limitations,
        )
        for m in data.metrics
    ]

    return VideoAnalyticsResponse(
        video_id=data.video_id,
        channel_id=data.channel_id,
        title=data.title,
        duration_seconds=data.duration_seconds,
        period_start=data.period_start.isoformat(),
        period_end=data.period_end.isoformat(),
        n_days_with_data=data.n_days_with_data,
        metrics=metric_schemas,
        compliance_notice=data.compliance_notice,
    )
