"""Domain persistence models package for miConte.

Exports all SQLAlchemy 2.0 ORM models to ensure declarative mappings
are registered with Base.metadata for migrations and repositories.
"""

from miconte.models.analysis import AnalysisRun, Recommendation, SyncRun
from miconte.models.channel import Channel, ChannelPublicSnapshot
from miconte.models.metrics import ChannelDailyMetric, VideoDailyMetric, VideoPeriodMetric
from miconte.models.reporting import ReportingReportIngestion
from miconte.models.session import UserSession
from miconte.models.user import OAuthConnection, User
from miconte.models.video import Video, VideoPublicSnapshot
from miconte.persistence.base import Base

__all__ = [
    "AnalysisRun",
    "Base",
    "Channel",
    "ChannelDailyMetric",
    "ChannelPublicSnapshot",
    "OAuthConnection",
    "Recommendation",
    "ReportingReportIngestion",
    "SyncRun",
    "User",
    "UserSession",
    "Video",
    "VideoDailyMetric",
    "VideoPeriodMetric",
    "VideoPublicSnapshot",
]
