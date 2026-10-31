"""Pure data models for the miConte recommendations rules engine.

No FastAPI, SQLAlchemy, network or LLM dependencies permitted here.
All types are plain Python dataclasses.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class RecommendationSignal:
    """Aggregate inputs the rules engine evaluates against a single video.

    All metric values are already computed (via miconte.statistics) before
    being passed here.  The engine itself performs no I/O and applies only
    threshold comparisons on these scalars.

    Fields prefixed ``channel_`` are baseline medians computed across all
    videos in the channel with sufficient data (n_videos_baseline >= 10).
    """

    channel_id: uuid.UUID
    video_id: uuid.UUID | None

    # Per-video computed metrics (None = data unavailable for this period)
    apv: float | None = None
    """Average Percentage Viewed: average_view_duration_s / duration_s (ratio 0-1)."""
    ctr: float | None = None
    """Click-Through Rate from thumbnail impressions (ratio 0-1)."""
    er: float | None = None
    """Engagement Rate: (likes + comments + shares) / views (ratio)."""
    nsc_1k: float | None = None
    """Net Subscriber Conversion per 1 000 views."""
    velocity_24h: float | None = None
    """Normalized first-day views: video_day1_views / median(channel_day1_views)."""

    # Channel baseline medians (None = insufficient channel history)
    channel_apv_median: float | None = None
    channel_ctr_median: float | None = None
    channel_er_median: float | None = None
    channel_velocity_median: float | None = None

    # Snapshot-based fields (Path A — cumulative counts from YouTube Data API)
    snapshot_view_count: int | None = None
    """Cumulative view count from the latest VideoPublicSnapshot."""
    channel_view_count_median: float | None = None
    """Median view count across all channel videos with snapshot data."""

    n_videos_baseline: int = 0
    """Number of channel videos with data used to compute baselines."""

    data_source: str = "daily"
    """Origin of the metrics: 'daily' (Analytics API) or 'snapshot' (Data API)."""

    period_start: date | None = None
    period_end: date | None = None


@dataclass
class RecommendationResult:
    """Output of one rule evaluated against a RecommendationSignal.

    ``triggered`` indicates whether the rule's threshold condition was met.
    Only triggered results are normally surfaced to the caller, but the engine
    returns all of them so callers can audit which rules fired vs. which did not.

    Language in ``title`` and ``description`` must be strictly associative
    (observational) — never causal.  Phrases like "is associated with",
    "shows a pattern consistent with", "was observed to be below" are correct.
    Phrases like "causes", "leads to", "will result in" are prohibited.
    """

    rule_code: str
    triggered: bool
    priority: str
    """'high', 'medium', 'low', or 'info'."""
    title: str
    description: str
    metrics_evidence: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
