"""Typed exceptions for official YouTube API clients."""

from typing import Any


class YouTubeAPIError(Exception):
    """Base exception for all YouTube API operations."""

    def __init__(self, message: str, status_code: int | None = None, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details


class QuotaExceededError(YouTubeAPIError):
    """Raised when YouTube Data or Analytics API quota limit has been reached."""


class InsufficientPermissionsError(YouTubeAPIError):
    """Raised when access is forbidden due to missing scopes or lack of resource ownership."""


class TokenExpiredError(YouTubeAPIError):
    """Raised when access token has expired or credentials are invalid (HTTP 401)."""


class ResourceNotFoundError(YouTubeAPIError):
    """Raised when requested channel, playlist, video, or report job does not exist."""


class InvalidQueryError(YouTubeAPIError):
    """Raised when invalid parameters, unsupported dimension combinations, or filters are sent."""


class OAuthError(YouTubeAPIError):
    """Raised when OAuth authorization flow, code exchange, or state verification fails."""


class InvalidGrantError(OAuthError):
    """Raised when Google rejects a refresh token with error=invalid_grant.

    This indicates the user has revoked consent from Google's account settings,
    the refresh token has expired (older than 6 months of inactivity), or the
    token was invalidated by a password change. All local API data associated
    with the consent must be deleted when this error is raised.
    """


def parse_google_api_error(
    status_code: int,
    response_data: dict[str, Any] | None = None,
    raw_text: str = "",
) -> YouTubeAPIError:
    """Parse Google API error response into a typed exception without exposing secrets.

    Handles two distinct Google error formats:
    - Data API format: {"error": {"code": N, "message": "...", "errors": [...]}}
    - OAuth token endpoint format: {"error": "invalid_grant", "error_description": "..."}
    """
    data = response_data if isinstance(response_data, dict) else {}

    # OAuth token endpoint uses a flat string for the error field
    error_field = data.get("error")
    if isinstance(error_field, str):
        error_code = error_field
        message = (
            data.get("error_description")
            or raw_text
            or f"OAuth error: {error_code}"
        )
        if error_code == "invalid_grant":
            return InvalidGrantError(
                message=f"Google revoked consent (invalid_grant): {message}",
                status_code=status_code,
            )
        return OAuthError(message=f"OAuth token error ({error_code}): {message}", status_code=400)

    # Data API nested format
    error_dict: dict[str, Any] = error_field if isinstance(error_field, dict) else {}
    message = (
        error_dict.get("message")
        or data.get("error_description")
        or raw_text
        or f"Google API error with HTTP status {status_code}"
    )

    # Check reason in error items
    errors_list: list[Any] = error_dict.get("errors", [])
    reasons = [item.get("reason", "") for item in errors_list if isinstance(item, dict)]

    if status_code == 401:
        return TokenExpiredError(message=f"Authentication failed: {message}", status_code=401)

    if status_code == 403:
        quota_reasons = ("quotaExceeded", "rateLimitExceeded", "userRateLimitExceeded")
        if any(r in quota_reasons for r in reasons):
            return QuotaExceededError(
                message=f"YouTube API quota exceeded: {message}",
                status_code=403,
                details=errors_list,
            )
        return InsufficientPermissionsError(
            message=f"Forbidden: {message}",
            status_code=403,
            details=errors_list,
        )

    if status_code == 404:
        return ResourceNotFoundError(message=f"Resource not found: {message}", status_code=404)

    if status_code == 400:
        return InvalidQueryError(message=f"Invalid request parameters: {message}", status_code=400)

    return YouTubeAPIError(
        message=f"YouTube API error ({status_code}): {message}",
        status_code=status_code,
    )
