"""OAuth 2.0 Web Server endpoints for YouTube authorization."""

from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict

from miconte.api.deps import CurrentUserDep, OAuthServiceDep, OptionalUserDep, SettingsDep
from miconte.integrations.youtube.dto import YouTubeChannelDTO
from miconte.integrations.youtube.exceptions import (
    InsufficientPermissionsError,
    OAuthError,
    YouTubeAPIError,
)
from miconte.security.exceptions import SecurityAuthorizationError

router = APIRouter(prefix="/api/v1/oauth/youtube", tags=["oauth"])


class AuthorizeResponse(BaseModel):
    """Payload containing authorization URL and state token."""

    model_config = ConfigDict(frozen=True)

    authorization_url: str
    state: str


class ConnectionStatusResponse(BaseModel):
    """Payload exposing connection health without leaking tokens."""

    model_config = ConfigDict(frozen=True)

    is_connected: bool
    external_channel_id: str
    is_active: bool
    granted_scopes: str
    token_expires_at: Any | None = None


class DisconnectRequest(BaseModel):
    """Request to revoke and disconnect an authorized channel for the current user."""

    channel_id: str


class DisconnectResponse(BaseModel):
    """Confirmation of disconnection distinguishing local purge from remote revocation."""

    model_config = ConfigDict(frozen=True)

    channel_id: str
    local_disconnected: bool
    remote_revoked: bool
    details: str


@router.get("/authorize", response_model=AuthorizeResponse)
def get_authorization_url(
    current_user: CurrentUserDep,
    oauth_service: OAuthServiceDep,
) -> AuthorizeResponse:
    """Generate authorization consent URL and CSRF state token for the authenticated user."""
    try:
        url, state = oauth_service.initiate_authorization(user_id=current_user.id)
        return AuthorizeResponse(authorization_url=url, state=state)
    except SecurityAuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/callback")
async def oauth_callback(
    code: str,
    state: str,
    oauth_service: OAuthServiceDep,
    settings: SettingsDep,
    current_user: OptionalUserDep = None,
) -> RedirectResponse:
    """Handle callback from Google, exchange code for tokens, persist connection, and redirect to frontend."""
    try:
        cur_uid = current_user.id if current_user else None
        await oauth_service.handle_callback(
            code=code,
            state=state,
            current_user_id=cur_uid,
        )
        return RedirectResponse(url=f"{settings.frontend_url}/connection", status_code=302)
    except SecurityAuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except InsufficientPermissionsError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient permissions: {exc}",
        ) from exc
    except OAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except YouTubeAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/status", response_model=ConnectionStatusResponse)
def get_connection_status(
    channel_id: str,
    current_user: CurrentUserDep,
    oauth_service: OAuthServiceDep,
) -> ConnectionStatusResponse:
    """Get active connection status for the authenticated user without exposing credentials."""
    status_dict = oauth_service.get_connection_status(
        user_id=current_user.id,
        external_channel_id=channel_id,
    )
    return ConnectionStatusResponse(**status_dict)


@router.post("/disconnect", response_model=DisconnectResponse)
async def disconnect_channel(
    req: DisconnectRequest,
    current_user: CurrentUserDep,
    oauth_service: OAuthServiceDep,
) -> DisconnectResponse:
    """Revoke authorization and deactivate channel connection for the authenticated user."""
    res = await oauth_service.disconnect(
        user_id=current_user.id,
        external_channel_id=req.channel_id,
    )
    return DisconnectResponse(
        channel_id=res.channel_id,
        local_disconnected=res.local_disconnected,
        remote_revoked=res.remote_revoked,
        details=res.details,
    )
