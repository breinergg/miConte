"""Production client for YouTube Analytics API v2."""

from datetime import date
from typing import Any

import httpx

from miconte.integrations.youtube.dto import (
    AnalyticsColumnHeaderDTO,
    AnalyticsReportDTO,
)
from miconte.integrations.youtube.exceptions import (
    InvalidQueryError,
    YouTubeAPIError,
    parse_google_api_error,
)

_ANALYTICS_API_BASE_URL = "https://youtubeanalytics.googleapis.com/v2"


class YouTubeAnalyticsClient:
    """Production client for YouTube Analytics API v2 reports.query."""

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = _ANALYTICS_API_BASE_URL,
    ) -> None:
        self._custom_client = http_client
        self.base_url = base_url.rstrip("/")

    async def query_report(
        self,
        access_token: str,
        start_date: date,
        end_date: date,
        metrics: list[str],
        dimensions: list[str] | None = None,
        filters: str | None = None,
        sort: str | None = None,
        max_results: int | None = None,
        start_index: int | None = None,
    ) -> AnalyticsReportDTO:
        """Execute reports.query against YouTube Analytics API v2.

        Enforces local pre-validation of unsupported dimension combinations.
        """
        if not access_token:
            raise YouTubeAPIError("Access token is required for YouTube Analytics API queries")

        if start_date > end_date:
            msg = f"startDate ({start_date}) cannot be after endDate ({end_date})"
            raise InvalidQueryError(msg)

        if not metrics:
            raise InvalidQueryError("At least one metric must be specified")

        # Local validation: dimensions=video,day is rejected by YouTube Analytics API
        if dimensions:
            dim_set = {d.strip().lower() for d in dimensions}
            if "video" in dim_set and "day" in dim_set:
                raise InvalidQueryError(
                    "Combination 'dimensions=video,day' is unsupported by YouTube Analytics API. "
                    "Use dimensions=day with filters=video==<ID> for single-video daily series, "
                    "or dimensions=video with sort=-views for channel-level video aggregates."
                )

        params: dict[str, Any] = {
            "ids": "channel==MINE",
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "metrics": ",".join(metrics),
        }

        if dimensions:
            params["dimensions"] = ",".join(dimensions)
        if filters:
            params["filters"] = filters
        if sort:
            params["sort"] = sort
        if max_results is not None:
            params["maxResults"] = max_results
        if start_index is not None:
            params["startIndex"] = start_index

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        url = f"{self.base_url}/reports"

        client = self._custom_client or httpx.AsyncClient(timeout=30.0)
        try:
            resp = await client.get(url, params=params, headers=headers)
        except httpx.RequestError as exc:
            msg = f"HTTP transport error communicating with YouTube Analytics API: {exc}"
            raise YouTubeAPIError(msg) from exc
        finally:
            if self._custom_client is None:
                await client.aclose()

        if not resp.is_success:
            try:
                error_json = resp.json()
            except Exception:
                error_json = None
            raise parse_google_api_error(resp.status_code, error_json, resp.text)

        data = resp.json()
        headers_raw = data.get("columnHeaders", [])
        column_headers = [
            AnalyticsColumnHeaderDTO(
                name=h["name"],
                column_type=h.get("columnType", "UNKNOWN"),
                data_type=h.get("dataType", "STRING"),
            )
            for h in headers_raw
        ]

        rows = data.get("rows", [])
        return AnalyticsReportDTO(column_headers=column_headers, rows=rows)
