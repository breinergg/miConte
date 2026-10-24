"""Bounded CLI diagnostic probe for Phase 2 live verification of YouTube APIs.

Usage (requires local credentials in environment or .env, never committed to Git):
    .venv/bin/python -m miconte.validation.live_probe

Environment variables checked (optional, for live verification only):
    MICONTE_YOUTUBE_API_KEY
    MICONTE_YOUTUBE_OAUTH_ACCESS_TOKEN
    MICONTE_YOUTUBE_TEST_CHANNEL_ID
    MICONTE_YOUTUBE_REPORTING_JOB_ID
"""

import json
import os
from datetime import UTC, datetime, timedelta

import httpx

from miconte.validation.youtube_phase2 import (
    YouTubeAPIError,
    YouTubePhase2Validator,
)


def run_live_probe() -> dict[str, object]:
    """Execute minimal, quota-safe live probes if local credentials exist."""
    api_key = os.environ.get("MICONTE_YOUTUBE_API_KEY")
    oauth_token = os.environ.get("MICONTE_YOUTUBE_OAUTH_ACCESS_TOKEN")
    test_channel_id = os.environ.get("MICONTE_YOUTUBE_TEST_CHANNEL_ID")
    reporting_job_id = os.environ.get("MICONTE_YOUTUBE_REPORTING_JOB_ID")

    summary: dict[str, object] = {
        "has_api_key": bool(api_key),
        "has_oauth_token": bool(oauth_token),
        "has_test_channel_id": bool(test_channel_id),
        "checks": {},
    }
    checks: dict[str, object] = {}
    summary["checks"] = checks

    if not api_key and not oauth_token:
        summary["overall_status"] = "documented_not_tested_missing_local_credentials"
        return summary

    with httpx.Client(timeout=15.0) as client:
        validator = YouTubePhase2Validator(
            http_client=client,
            api_key=api_key,
            oauth_access_token=oauth_token,
        )

        if test_channel_id:
            try:
                channel = validator.fetch_channel_by_id(test_channel_id)
                if channel is not None:
                    video_ids = validator.list_upload_video_ids(
                        channel.uploads_playlist_id,
                        max_results_per_page=5,
                        max_pages=1,
                    )
                    videos = validator.fetch_videos_by_ids(video_ids[:5])
                    checks["data_api_v3"] = {
                        "status": "verified_live",
                        "channel_id": channel.channel_id,
                        "sample_videos_fetched": len(videos),
                    }
                else:
                    checks["data_api_v3"] = {"status": "empty_response"}
            except YouTubeAPIError as exc:
                checks["data_api_v3"] = {
                    "status": "error",
                    "http_status": exc.status_code,
                    "reason": exc.reason,
                }

        if oauth_token:
            end_dt = datetime.now(tz=UTC).date()
            start_dt = end_dt - timedelta(days=14)
            try:
                report = validator.query_analytics_report(
                    start_date=start_dt,
                    end_date=end_dt,
                    metrics=[
                        "views",
                        "estimatedMinutesWatched",
                        "averageViewDuration",
                        "averageViewPercentage",
                        "likes",
                        "comments",
                        "shares",
                        "subscribersGained",
                        "subscribersLost",
                    ],
                    dimensions=["day"],
                )
                checks["analytics_api_v2_daily"] = {
                    "status": "verified_live",
                    "rows_returned": len(report.rows),
                }
            except YouTubeAPIError as exc:
                checks["analytics_api_v2_daily"] = {
                    "status": "permission_error" if exc.status_code == 403 else "error",
                    "http_status": exc.status_code,
                    "reason": exc.reason,
                }

            try:
                report_types = validator.list_reporting_report_types()
                reach_available = any(
                    rt.report_type_id == "channel_reach_basic_a1" for rt in report_types
                )
                reporting_info: dict[str, object] = {
                    "status": "verified_live" if reach_available else "unavailable",
                    "channel_reach_basic_a1_listed": reach_available,
                }
                if reporting_job_id:
                    job_status = validator.check_reporting_job_reports(reporting_job_id)
                    reporting_info["job_status"] = job_status.status
                    reporting_info["generated_files_count"] = len(job_status.reports)
                checks["reporting_api_v1"] = reporting_info
            except YouTubeAPIError as exc:
                checks["reporting_api_v1"] = {
                    "status": "permission_error" if exc.status_code == 403 else "error",
                    "http_status": exc.status_code,
                    "reason": exc.reason,
                }

    summary["overall_status"] = "completed_live_probes"
    return summary


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(run_live_probe(), indent=2))
