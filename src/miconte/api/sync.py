"""FastAPI endpoints for data synchronization and periodic scheduler management."""

import contextlib
import json
import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from miconte.api.deps import CurrentUserDep, SchedulerDep, SyncServiceDep
from miconte.integrations.youtube.exceptions import (
    InsufficientPermissionsError,
    InvalidQueryError,
    ResourceNotFoundError,
    YouTubeAPIError,
)
from miconte.security.exceptions import SecurityAuthorizationError
from miconte.services.sync_dto import (
    SchedulerStatusDTO,
    SynchronizableChannelDTO,
    SyncRunResultDTO,
    SyncStageResultDTO,
    SyncTriggerRequestDTO,
)

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


class SyncRunResponse(BaseModel):
    """Response representing a synchronization execution record."""

    model_config = ConfigDict(frozen=True)

    sync_run_id: uuid.UUID
    channel_id: uuid.UUID
    sync_type: str
    status: str
    started_at: str
    completed_at: str | None = None
    records_processed: int = 0
    stages: list[SyncStageResultDTO] = []
    error_message: str | None = None
    is_recoverable: bool = False


@router.get("/channels", response_model=list[SynchronizableChannelDTO])
def list_synchronizable_channels(
    current_user: CurrentUserDep,
    sync_service: SyncServiceDep,
) -> list[SynchronizableChannelDTO]:
    """List all YouTube channels owned by the authenticated user with sync status."""
    return sync_service.list_user_synchronizable_channels(user_id=current_user.id)


@router.post("/channels/{channel_id}/trigger", response_model=SyncRunResultDTO)
async def trigger_channel_sync(
    channel_id: uuid.UUID,
    current_user: CurrentUserDep,
    sync_service: SyncServiceDep,
    scheduler: SchedulerDep,
    request: SyncTriggerRequestDTO | None = None,
) -> SyncRunResultDTO:
    """Manually trigger synchronization for a specific channel owned by the authenticated user."""
    req = request or SyncTriggerRequestDTO()
    try:
        # Use scheduler's channel lock to avoid racing against periodic sync
        return await scheduler.trigger_channel_sync(
            user_id=current_user.id,
            channel_id=channel_id,
            sync_types=req.sync_types,
            max_videos=req.max_videos,
            session=sync_service.session,
        )
    except SecurityAuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except ResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except InsufficientPermissionsError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient permissions: {exc}",
        ) from exc
    except InvalidQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        # Concurrency conflict
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except YouTubeAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.get("/channels/{channel_id}/runs", response_model=list[SyncRunResponse])
def list_channel_sync_runs(
    channel_id: uuid.UUID,
    current_user: CurrentUserDep,
    sync_service: SyncServiceDep,
    limit: int = 50,
) -> list[SyncRunResponse]:
    """Retrieve audit history of sync runs for a channel owned by the authenticated user."""
    channel = sync_service.channel_repo.get_by_id(channel_id)
    if not channel or channel.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel {channel_id} not found or not owned by user",
        )

    runs = sync_service.analysis_repo.list_sync_runs(channel_id=channel_id, limit=limit)
    responses: list[SyncRunResponse] = []
    for r in runs:
        stages: list[SyncStageResultDTO] = []
        if r.error_message:
            with contextlib.suppress(Exception):
                parsed = json.loads(r.error_message)
                if isinstance(parsed, dict) and "stages" in parsed:
                    stages = [SyncStageResultDTO(**s) for s in parsed["stages"]]

        responses.append(
            SyncRunResponse(
                sync_run_id=r.id,
                channel_id=r.channel_id,
                sync_type=r.sync_type,
                status=r.status,
                started_at=r.started_at.isoformat(),
                completed_at=r.completed_at.isoformat() if r.completed_at else None,
                records_processed=r.records_processed,
                stages=stages,
                error_message=r.error_message,
                is_recoverable=False,
            )
        )
    return responses


@router.get("/runs/{sync_run_id}", response_model=SyncRunResponse)
def get_sync_run_details(
    sync_run_id: uuid.UUID,
    current_user: CurrentUserDep,
    sync_service: SyncServiceDep,
) -> SyncRunResponse:
    """Retrieve detailed execution information for a specific sync run."""
    run = sync_service.analysis_repo.get_sync_run(sync_run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SyncRun {sync_run_id} not found",
        )

    channel = sync_service.channel_repo.get_by_id(run.channel_id)
    if not channel or channel.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SyncRun {sync_run_id} not found or belongs to another user",
        )

    stages: list[SyncStageResultDTO] = []
    if run.error_message:
        with contextlib.suppress(Exception):
            parsed = json.loads(run.error_message)
            if isinstance(parsed, dict) and "stages" in parsed:
                stages = [SyncStageResultDTO(**s) for s in parsed["stages"]]

    return SyncRunResponse(
        sync_run_id=run.id,
        channel_id=run.channel_id,
        sync_type=run.sync_type,
        status=run.status,
        started_at=run.started_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        records_processed=run.records_processed,
        stages=stages,
        error_message=run.error_message,
        is_recoverable=False,
    )


@router.get("/scheduler/status", response_model=SchedulerStatusDTO)
def get_scheduler_status(
    scheduler: SchedulerDep,
) -> SchedulerStatusDTO:
    """Check periodic synchronization scheduler runtime health and status."""
    return scheduler.get_status()
