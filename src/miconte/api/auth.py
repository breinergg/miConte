"""Google OpenID Connect authentication endpoints.

Provides login initiation, callback handling, session management, and logout.
This router is entirely separate from the YouTube channel authorization router
(/api/v1/oauth/). The two flows share Google Cloud credentials but use
different redirect URIs, different scopes, and completely separate state stores.

Cookie policy:
- Session cookies are HttpOnly and SameSite=Lax.
- In production the Secure flag is set (HTTPS only).
- Tokens are never exposed to JavaScript.
"""

import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from miconte.api.deps import CurrentUserDep, DbSessionDep, SettingsDep
from miconte.core.config import Settings
from miconte.models.user import User
from miconte.persistence.repositories.session_repo import SessionRepository
from miconte.services.google_auth_service import GoogleAuthService, GoogleOIDCError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class UserResponse(BaseModel):
    """Public user representation — no credentials exposed."""

    id: str
    email: str
    full_name: str | None = None
    has_google_login: bool

    model_config = {"from_attributes": True}


def _build_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        has_google_login=user.google_sub is not None,
    )


def _set_session_cookie(
    response: JSONResponse | RedirectResponse,
    settings: Settings,
    token: str,
) -> None:
    """Attach the session cookie with the appropriate security flags."""
    is_prod = settings.environment == "production"
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=is_prod,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: JSONResponse | RedirectResponse, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
    )


@router.get(
    "/google/login",
    summary="Initiate Google OpenID Connect login",
    description=(
        "Generates a PKCE pair and anti-CSRF state token, "
        "then redirects the browser to Google's authorization endpoint. "
        "Scope: openid email profile."
    ),
)
async def google_login(settings: SettingsDep) -> RedirectResponse:
    """Start the Google OIDC login flow."""
    svc = GoogleAuthService(session=None, settings=settings)  # type: ignore[arg-type]
    try:
        auth_url, _state = svc.build_login_url()
    except GoogleOIDCError as exc:
        logger.error("OIDC login initiation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google login is not configured",
        ) from exc
    return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)


@router.get(
    "/google/callback",
    summary="Google OIDC callback — validates state, issues session cookie",
    include_in_schema=False,
)
async def google_callback(
    code: str,
    state: str,
    session: DbSessionDep,
    settings: SettingsDep,
    error: str | None = None,
) -> RedirectResponse:
    """Process the Google authorization callback.

    1. Validates the anti-CSRF state token (single-use).
    2. Exchanges the authorization code for an ID token (PKCE).
    3. Verifies the ID token (signature, iss, aud, exp).
    4. Finds or creates the local User by stable Google `sub`.
    5. Creates a server-side session and sets an HttpOnly cookie.
    6. Redirects to the frontend.
    """
    if error:
        logger.warning("Google OIDC callback received error: %s", error)
        return RedirectResponse(
            url=f"{settings.frontend_url}/?auth_error=access_denied",
            status_code=status.HTTP_302_FOUND,
        )

    svc = GoogleAuthService(session=session, settings=settings)

    try:
        # Consume the state token (validates anti-CSRF, single-use)
        # Returns both PKCE verifier and nonce bound at login-initiation time
        code_verifier, expected_nonce = svc.login_store.consume(state)
    except ValueError as exc:
        logger.warning("OIDC state validation failed: %s", exc)
        return RedirectResponse(
            url=f"{settings.frontend_url}/?auth_error=invalid_state",
            status_code=status.HTTP_302_FOUND,
        )

    try:
        token_data = await svc.exchange_code(code=code, code_verifier=code_verifier)
    except GoogleOIDCError as exc:
        logger.warning("OIDC code exchange failed: %s", exc)
        return RedirectResponse(
            url=f"{settings.frontend_url}/?auth_error=token_exchange_failed",
            status_code=status.HTTP_302_FOUND,
        )

    raw_id_token = token_data.get("id_token")
    if not raw_id_token:
        logger.error("Google token response missing id_token")
        return RedirectResponse(
            url=f"{settings.frontend_url}/?auth_error=missing_id_token",
            status_code=status.HTTP_302_FOUND,
        )

    try:
        claims = await svc.verify_id_token(raw_id_token, expected_nonce=expected_nonce)
    except GoogleOIDCError as exc:
        logger.warning("OIDC id_token verification failed: %s", exc)
        return RedirectResponse(
            url=f"{settings.frontend_url}/?auth_error=invalid_token",
            status_code=status.HTTP_302_FOUND,
        )

    sub = claims.get("sub")
    email = claims.get("email")
    if not sub or not email:
        logger.error("OIDC token missing sub or email claim")
        return RedirectResponse(
            url=f"{settings.frontend_url}/?auth_error=missing_claims",
            status_code=status.HTTP_302_FOUND,
        )

    try:
        user = svc.get_or_create_user(
            sub=sub,
            email=email,
            full_name=claims.get("name"),
        )
    except GoogleOIDCError as exc:
        logger.warning("OIDC user provisioning failed: %s", exc)
        return RedirectResponse(
            url=f"{settings.frontend_url}/?auth_error=account_inactive",
            status_code=status.HTTP_302_FOUND,
        )

    session_token = svc.create_session(user_id=user.id)
    session.commit()

    redirect = RedirectResponse(
        url=f"{settings.frontend_url}/",
        status_code=status.HTTP_302_FOUND,
    )
    _set_session_cookie(redirect, settings, session_token)
    return redirect


@router.post(
    "/logout",
    summary="Revoke the current session and clear the session cookie",
)
async def logout(
    request: Request,
    session: DbSessionDep,
    settings: SettingsDep,
) -> JSONResponse:
    """Invalidate the current server-side session and clear the cookie.

    Safe to call even when no session is active.
    """
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        repo = SessionRepository(session)
        repo.delete_by_token(token)
        session.commit()

    response = JSONResponse(content={"detail": "Logged out successfully"})
    _clear_session_cookie(response, settings)
    return response


@router.get(
    "/me",
    summary="Return the currently authenticated user",
    response_model=UserResponse,
)
async def me(current_user: CurrentUserDep) -> UserResponse:
    """Return public information about the currently authenticated user."""
    return _build_user_response(current_user)
