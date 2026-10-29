"""Repository for synchronization logs, analysis runs, and recommendations."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from miconte.models.analysis import AnalysisRun, Recommendation, SyncRun
from miconte.models.reporting import ReportingReportIngestion


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

    def get_sync_run(self, sync_run_id: uuid.UUID) -> SyncRun | None:
        """Fetch a specific SyncRun by ID."""
        return self.session.get(SyncRun, sync_run_id)

    def get_latest_sync_run(
        self,
        channel_id: uuid.UUID,
        sync_type: str | None = None,
    ) -> SyncRun | None:
        """Fetch the most recent SyncRun for a channel, optionally filtered by type."""
        stmt = select(SyncRun).where(SyncRun.channel_id == channel_id)
        if sync_type:
            stmt = stmt.where(SyncRun.sync_type == sync_type)
        stmt = stmt.order_by(SyncRun.started_at.desc()).limit(1)
        return self.session.execute(stmt).scalar_one_or_none()

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

    def get_processed_report_ids(self, channel_id: uuid.UUID) -> set[str]:
        """Return all Reporting API report IDs that were successfully ingested for a channel."""
        stmt = select(ReportingReportIngestion.report_id).where(
            ReportingReportIngestion.channel_id == channel_id,
        )
        return set(self.session.execute(stmt).scalars().all())

    def get_latest_ingestion_for_period(
        self,
        channel_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
        job_id: str,
    ) -> ReportingReportIngestion | None:
        """Return the most recently ingested report for a given period window and job.

        Used to detect restatements: if YouTube re-issues a report for the same
        (job_id, start, end) window with a newer create_time, the caller compares it
        against the existing record to decide whether re-processing is warranted.

        job_id scoping is mandatory: different YouTube jobs (different report types)
        can legitimately cover the same calendar period without being versions of each
        other.  Comparing across jobs would produce nonsensical version ordering and
        could block a new job type from being ingested at all.
        """
        stmt = (
            select(ReportingReportIngestion)
            .where(
                ReportingReportIngestion.channel_id == channel_id,
                ReportingReportIngestion.job_id == job_id,
                ReportingReportIngestion.report_period_start == period_start,
                ReportingReportIngestion.report_period_end == period_end,
            )
            .order_by(ReportingReportIngestion.report_create_time.desc().nullslast())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def record_report_ingestion(
        self,
        *,
        channel_id: uuid.UUID,
        report_id: str,
        job_id: str,
        report_period_start: datetime | None = None,
        report_period_end: datetime | None = None,
        report_create_time: datetime | None = None,
        rows_ingested: int = 0,
    ) -> ReportingReportIngestion:
        """Persist a successful Reporting API report ingestion record.

        Must be called only after all metric rows have been flushed. If the
        enclosing transaction is rolled back, this record is rolled back too,
        preserving atomicity: no ingestion record exists for a failed sync.
        """
        ingestion = ReportingReportIngestion(
            channel_id=channel_id,
            report_id=report_id,
            job_id=job_id,
            report_period_start=report_period_start,
            report_period_end=report_period_end,
            report_create_time=report_create_time,
            rows_ingested=rows_ingested,
        )
        self.session.add(ingestion)
        self.session.flush()
        return ingestion

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

