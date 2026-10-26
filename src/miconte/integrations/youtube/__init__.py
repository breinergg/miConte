"""YouTube official API integration clients and data transfer objects."""

from miconte.integrations.youtube.analytics_v2 import YouTubeAnalyticsClient
from miconte.integrations.youtube.data_v3 import YouTubeDataClient
from miconte.integrations.youtube.dto import (
    AnalyticsColumnHeaderDTO,
    AnalyticsReportDTO,
    OAuthTokenResponseDTO,
    ReportingJobDTO,
    ReportingReachRowDTO,
    ReportingReportDTO,
    YouTubeChannelDTO,
    YouTubePlaylistItemDTO,
    YouTubeVideoDTO,
)
from miconte.integrations.youtube.exceptions import (
    InsufficientPermissionsError,
    InvalidQueryError,
    OAuthError,
    QuotaExceededError,
    ResourceNotFoundError,
    TokenExpiredError,
    YouTubeAPIError,
)
from miconte.integrations.youtube.reporting_v1 import YouTubeReportingClient

__all__ = [
    "AnalyticsColumnHeaderDTO",
    "AnalyticsReportDTO",
    "InsufficientPermissionsError",
    "InvalidQueryError",
    "OAuthError",
    "OAuthTokenResponseDTO",
    "QuotaExceededError",
    "ReportingJobDTO",
    "ReportingReachRowDTO",
    "ReportingReportDTO",
    "ResourceNotFoundError",
    "TokenExpiredError",
    "YouTubeAPIError",
    "YouTubeAnalyticsClient",
    "YouTubeChannelDTO",
    "YouTubeDataClient",
    "YouTubePlaylistItemDTO",
    "YouTubeReportingClient",
    "YouTubeVideoDTO",
]
