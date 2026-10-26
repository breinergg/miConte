"""Production client for YouTube Reporting API v1."""

import csv
import io
import ipaddress
import urllib.parse
from datetime import date, datetime
from typing import Any

import httpx

from miconte.integrations.youtube.dto import (
    ReportingJobDTO,
    ReportingReachRowDTO,
    ReportingReportDTO,
)
from miconte.integrations.youtube.exceptions import (
    InvalidQueryError,
    YouTubeAPIError,
    parse_google_api_error,
)

_REPORTING_API_BASE_URL = "https://youtubereporting.googleapis.com/v1"
_EXPECTED_REACH_COLUMNS = {
    "date",
    "channel_id",
    "video_id",
    "live_or_on_demand",
    "video_thumbnail_impressions",
}
_MAX_CSV_BYTES = 50 * 1024 * 1024  # 50 MB safety ceiling for CSV downloads
_ALLOWED_REPORTING_HOSTS = {
    "youtubereporting.googleapis.com",
    "storage.googleapis.com",
}


def validate_reporting_download_url(download_url: str) -> None:
    """Validate that report download URL points to an authorized Google HTTPS endpoint.

    Prevents SSRF, private network probing, and credential exfiltration.
    """
    if not download_url or not isinstance(download_url, str):
        raise InvalidQueryError("Download URL must be a non-empty string")

    parsed = urllib.parse.urlparse(download_url.strip())
    if parsed.scheme.lower() != "https":
        raise InvalidQueryError(f"Download URL must use HTTPS scheme, got '{parsed.scheme}'")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise InvalidQueryError("Download URL missing valid hostname")

    # Reject IP addresses (IPv4 and IPv6) to avoid private network probing (SSRF)
    try:
        ipaddress.ip_address(hostname)
        msg = f"Direct IP addresses are prohibited for report downloads: {hostname}"
        raise InvalidQueryError(msg)
    except ValueError:
        pass  # Hostname is a domain name, proceed with domain verification

    # Disallow localhost or internal single-label hosts
    if hostname == "localhost" or "." not in hostname:
        raise InvalidQueryError(f"Local and internal hostnames are prohibited: {hostname}")

    # Check non-standard ports
    if parsed.port and parsed.port != 443:
        msg = f"Non-standard port '{parsed.port}' prohibited for report downloads"
        raise InvalidQueryError(msg)

    # Ensure hostname is an authorized Google domain
    is_allowed = (
        hostname in _ALLOWED_REPORTING_HOSTS
        or hostname.endswith(".googleapis.com")
        or hostname.endswith(".googleusercontent.com")
    )
    if not is_allowed:
        raise InvalidQueryError(
            f"Download URL destination '{hostname}' is not an authorized Google reporting domain"
        )


class YouTubeReportingClient:
    """Production client for YouTube Reporting API v1 bulk reports."""

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = _REPORTING_API_BASE_URL,
    ) -> None:
        self._custom_client = http_client
        self.base_url = base_url.rstrip("/")

    async def _send_request(
        self,
        method: str,
        path: str,
        access_token: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute authenticated request against Reporting API."""
        if not access_token:
            raise YouTubeAPIError("Access token required for YouTube Reporting API")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        url = f"{self.base_url}/{path.lstrip('/')}"

        client = self._custom_client or httpx.AsyncClient(timeout=30.0)
        try:
            resp = await client.request(
                method, url, params=params, json=json_data, headers=headers
            )
        except httpx.RequestError as exc:
            raise YouTubeAPIError(f"Transport error with Reporting API: {exc}") from exc
        finally:
            if self._custom_client is None:
                await client.aclose()

        if not resp.is_success:
            try:
                error_json = resp.json()
            except Exception:
                error_json = None
            raise parse_google_api_error(resp.status_code, error_json, resp.text)

        return resp.json() if resp.content else {}

    async def list_report_types(self, access_token: str) -> list[dict[str, Any]]:
        """List available report types for the channel."""
        data = await self._send_request("GET", "reportTypes", access_token=access_token)
        return data.get("reportTypes", [])  # type: ignore[no-any-return]

    async def create_job(
        self,
        access_token: str,
        report_type_id: str,
        name: str | None = None,
    ) -> ReportingJobDTO:
        """Create a recurring bulk reporting job."""
        payload = {
            "reportTypeId": report_type_id,
            "name": name or f"miConte {report_type_id}",
        }
        data = await self._send_request(
            "POST", "jobs", access_token=access_token, json_data=payload
        )
        create_raw = data.get("createTime")
        create_dt = (
            datetime.fromisoformat(create_raw.replace("Z", "+00:00"))
            if create_raw
            else None
        )

        return ReportingJobDTO(
            job_id=data["id"],
            report_type_id=data["reportTypeId"],
            name=data.get("name"),
            create_time=create_dt,
        )

    async def list_jobs(self, access_token: str) -> list[ReportingJobDTO]:
        """List all active reporting jobs."""
        data = await self._send_request("GET", "jobs", access_token=access_token)
        jobs = data.get("jobs", [])
        results: list[ReportingJobDTO] = []
        for j in jobs:
            c_raw = j.get("createTime")
            c_dt = datetime.fromisoformat(c_raw.replace("Z", "+00:00")) if c_raw else None
            results.append(
                ReportingJobDTO(
                    job_id=j["id"],
                    report_type_id=j["reportTypeId"],
                    name=j.get("name"),
                    create_time=c_dt,
                )
            )
        return results

    async def list_reports(self, access_token: str, job_id: str) -> list[ReportingReportDTO]:
        """List generated reports for a job.

        Note: May be empty if within the 48-hour generation window.
        """
        data = await self._send_request(
            "GET", f"jobs/{job_id}/reports", access_token=access_token
        )
        reports = data.get("reports", [])
        results: list[ReportingReportDTO] = []
        for r in reports:
            st_raw = r.get("startTime")
            et_raw = r.get("endTime")
            ct_raw = r.get("createTime")
            st_dt = datetime.fromisoformat(st_raw.replace("Z", "+00:00")) if st_raw else None
            et_dt = datetime.fromisoformat(et_raw.replace("Z", "+00:00")) if et_raw else None
            ct_dt = datetime.fromisoformat(ct_raw.replace("Z", "+00:00")) if ct_raw else None

            results.append(
                ReportingReportDTO(
                    report_id=r["id"],
                    job_id=r.get("jobId", job_id),
                    start_time=st_dt,
                    end_time=et_dt,
                    create_time=ct_dt,
                    download_url=r["downloadUrl"],
                )
            )
        return results

    async def download_report_csv(
        self,
        access_token: str,
        download_url: str,
    ) -> list[ReportingReachRowDTO]:
        """Download and validate a bulk CSV report file (channel_reach_basic_a1).

        Enforces SSRF validation, size caps, and secure header handling.
        """
        if not access_token:
            raise YouTubeAPIError("Access token required to download report CSV")

        # Validate URL before connecting
        validate_reporting_download_url(download_url)

        headers = {"Authorization": f"Bearer {access_token}"}
        client = self._custom_client or httpx.AsyncClient(timeout=60.0)
        try:
            resp = await client.get(download_url, headers=headers, follow_redirects=True)
            for redirect in resp.history:
                validate_reporting_download_url(str(redirect.url))
            validate_reporting_download_url(str(resp.url))

            if len(resp.content) > _MAX_CSV_BYTES:
                raise InvalidQueryError(
                    f"Report CSV exceeds maximum allowed size ({_MAX_CSV_BYTES} bytes)"
                )
        except httpx.RequestError as exc:
            raise YouTubeAPIError(f"Failed to download report CSV: {exc}") from exc
        finally:
            if self._custom_client is None:
                await client.aclose()

        if not resp.is_success:
            raise parse_google_api_error(resp.status_code, None, resp.text)

        csv_text = resp.text
        reader = csv.DictReader(io.StringIO(csv_text))
        if not reader.fieldnames:
            raise InvalidQueryError("Downloaded CSV is empty or has no header row")

        # Validate required columns
        header_set = {h.strip().lower() for h in reader.fieldnames}
        missing_cols = _EXPECTED_REACH_COLUMNS - header_set
        if missing_cols:
            raise InvalidQueryError(f"CSV missing expected reach report columns: {missing_cols}")

        rows: list[ReportingReachRowDTO] = []
        for r in reader:
            raw_date = r["date"].strip()
            if len(raw_date) == 8 and raw_date.isdigit():
                parsed_date = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8]))
            else:
                parsed_date = date.fromisoformat(raw_date)

            raw_impr = int(r["video_thumbnail_impressions"])
            raw_ctr = r.get("video_thumbnail_impressions_ctr")
            ctr_val = float(raw_ctr) if raw_ctr and raw_ctr.strip() else None

            rows.append(
                ReportingReachRowDTO(
                    date=parsed_date,
                    channel_id=r["channel_id"].strip(),
                    video_id=r["video_id"].strip(),
                    live_or_on_demand=r["live_or_on_demand"].strip(),
                    video_thumbnail_impressions=raw_impr,
                    video_thumbnail_impressions_ctr=ctr_val,
                )
            )

        return rows
