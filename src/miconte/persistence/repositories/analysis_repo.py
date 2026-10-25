"""Repository for synchronization logs, analysis runs, and recommendations."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from miconte.models.analysis import AnalysisRun, Recommendation, SyncRun


class AnalysisRepository:
    """Repository handling execution tracking and deterministic recommendations."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # -------------------------------------------------------------------------
    # Sync Runs
    # -------------------------------------------------------------------------
    def start_sync_run(
        self,
        *,
        channel_id: uuid.UUID,
        sync_type: str,
        status: str = "running",
    ) -> SyncRun:
        run = SyncRun(
            channel_id=channel_id,
            sync_type=sync_type,
            status=status,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def complete_sync_run(
        self,
        sync_run_id: uuid.UUID,
        *,
        records_processed: int,
        status: str = "completed",
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> SyncRun:
        run = self.session.get(SyncRun, sync_run_id)
        if run is None:
            raise ValueError(f"SyncRun with id '{sync_run_id}' not found.")
        run.records_processed = records_processed
        run.status = status
        run.error_message = error_message
        run.completed_at = completed_at or datetime.now().astimezone()
        self.session.flush()
        return run

    def list_sync_runs(
        self,
        channel_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> list[SyncRun]:
        stmt = (
            select(SyncRun)
            .where(SyncRun.channel_id == channel_id)
            .order_by(SyncRun.started_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())

    # -------------------------------------------------------------------------
    # Analysis Runs
    # -------------------------------------------------------------------------
    def start_analysis_run(
        self,
        *,
        channel_id: uuid.UUID,
        analysis_type: str,
        parameters: dict[str, Any] | None = None,
        video_id: uuid.UUID | None = None,
        status: str = "running",
    ) -> AnalysisRun:
        run = AnalysisRun(
            channel_id=channel_id,
            video_id=video_id,
            analysis_type=analysis_type,
            status=status,
            parameters=parameters or {},
        )
        self.session.add(run)
        self.session.flush()
        return run

    def complete_analysis_run(
        self,
        analysis_run_id: uuid.UUID,
        *,
        status: str = "completed",
        sample_size_n: int | None = None,
        summary_results: dict[str, Any] | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> AnalysisRun:
        run = self.session.get(AnalysisRun, analysis_run_id)
        if run is None:
            raise ValueError(f"AnalysisRun with id '{analysis_run_id}' not found.")
        run.status = status
        run.sample_size_n = sample_size_n
        run.summary_results = summary_results
        run.error_message = error_message
        run.completed_at = completed_at or datetime.now().astimezone()
        self.session.flush()
        return run

    def get_analysis_run(self, analysis_run_id: uuid.UUID) -> AnalysisRun | None:
        return self.session.get(AnalysisRun, analysis_run_id)

    # -------------------------------------------------------------------------
    # Recommendations
    # -------------------------------------------------------------------------
    def record_recommendation(
        self,
        *,
        analysis_run_id: uuid.UUID,
        channel_id: uuid.UUID,
        rule_code: str,
        title: str,
        description: str,
        priority: str = "medium",
        metrics_evidence: dict[str, Any] | None = None,
        video_id: uuid.UUID | None = None,
    ) -> Recommendation:
        rec = Recommendation(
            analysis_run_id=analysis_run_id,
            channel_id=channel_id,
            video_id=video_id,
            rule_code=rule_code,
            title=title,
            description=description,
            priority=priority,
            metrics_evidence=metrics_evidence or {},
        )
        self.session.add(rec)
        self.session.flush()
        return rec

    def list_recommendations(
        self,
        channel_id: uuid.UUID,
        *,
        video_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[Recommendation]:
        stmt = select(Recommendation).where(Recommendation.channel_id == channel_id)
        if video_id is not None:
            stmt = stmt.where(Recommendation.video_id == video_id)
        stmt = stmt.order_by(Recommendation.created_at.desc()).limit(limit)
        return list(self.session.execute(stmt).scalars().all())

