"""High-level orchestration service for YouTube OAuth 2.0 authorization and credentials."""

import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session

from miconte.core.config import Settings
from miconte.integrations.youtube.data_v3 import YouTubeDataClient
from miconte.integrations.youtube.dto import DisconnectResultDTO, YouTubeChannelDTO
from miconte.integrations.youtube.exceptions import (
    OAuthError,
    ResourceNotFoundError,
)
from miconte.persistence.repositories.channel_repo import ChannelRepository
from miconte.persistence.repositories.user_repo import UserRepository
from miconte.security.crypto import TokenEncryptionService, build_token_aad
from miconte.security.exceptions import SecurityAuthorizationError
from miconte.security.oauth import (
    OAuthTransactionStore,
    create_state_token,
    default_transaction_store,
    exchange_code_for_tokens,
    generate_authorization_url,
    generate_pkce_pair,
    refresh_oauth_token,
    revoke_oauth_token,
    verify_state_token,
)


class OAuthService:
    """Coordinates OAuth flows, secure encrypted persistence, and token lifecycle."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        crypto_service: TokenEncryptionService,
        http_client: httpx.AsyncClient | None = None,
        transaction_store: OAuthTransactionStore | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.crypto_service = crypto_service
        self.http_client = http_client
        self.transaction_store = transaction_store or default_transaction_store
        self.user_repo = UserRepository(session)
        self.channel_repo = ChannelRepository(session)

    def initiate_authorization(
        self,
        user_id: uuid.UUID,
        session_id: str | None = None,
    ) -> tuple[str, str]:
        """Generate PKCE pair, register single-use state transaction, and build auth URL."""
        user = self.user_repo.get_by_id(user_id)
        if not user or not user.is_active:
            raise SecurityAuthorizationError(f"Active user {user_id} not found")

        secret = self.settings.oauth_state_secret.get_secret_value()
        state_token, state_nonce = create_state_token(
            user_id=user_id,
            secret=secret,
            ttl_seconds=600,
            session_id=session_id,
        )

        verifier, challenge = generate_pkce_pair()
        self.transaction_store.register(
            state_nonce=state_nonce,
            user_id=user_id,
            code_verifier=verifier,
            ttl_seconds=600,
            session_id=session_id,
        )

        auth_url = generate_authorization_url(
            client_id=self.settings.youtube_client_id,
            redirect_uri=self.settings.youtube_redirect_uri,
            state=state_token,
            code_challenge=challenge,
        )
        return auth_url, state_token

    async def handle_callback(
        self,
        code: str,
        state: str,
        current_user_id: uuid.UUID | None = None,
        session_id: str | None = None,
    ) -> YouTubeChannelDTO:
        """Process callback from Google, validating state, user, and single-use transaction.

        CRITICAL SECURITY: Validation occurs BEFORE exchanging authorization code.
        """
        secret = self.settings.oauth_state_secret.get_secret_value()
        state_user_id, state_nonce, token_sid = verify_state_token(state=state, secret=secret)

        if current_user_id and current_user_id != state_user_id:
            raise SecurityAuthorizationError(
                "State token does not match currently authenticated user"
            )

        # Single-use check and PKCE verifier retrieval BEFORE token exchange
        effective_sid = session_id or token_sid
        code_verifier = self.transaction_store.consume(
            state_nonce=state_nonce,
            expected_user_id=state_user_id,
            expected_session_id=effective_sid,
        )

        # 1. Exchange authorization code for tokens with PKCE verifier
        tokens = await exchange_code_for_tokens(
            code=code,
            client_id=self.settings.youtube_client_id,
            client_secret=self.settings.youtube_client_secret.get_secret_value(),
            redirect_uri=self.settings.youtube_redirect_uri,
            code_verifier=code_verifier,
            http_client=self.http_client,
        )

        # 2. Query authorized channel identity using access token
        data_client = YouTubeDataClient(http_client=self.http_client)
        channel_dto = await data_client.get_channel(mine=True, access_token=tokens.access_token)
        channel_id = channel_dto.youtube_channel_id

        # 3. Check for existing connection to avoid overwriting valid refresh token with None
        existing_conn = self.user_repo.get_oauth_connection(
            user_id=state_user_id,
            external_channel_id=channel_id,
            platform="youtube",
        )

        # 4. Encrypt access token with AAD context binding
        aad_access = build_token_aad(
            user_id=str(state_user_id),
            platform="youtube",
            external_channel_id=channel_id,
            credential_kind="access",
        )
        encrypted_access = self.crypto_service.encrypt(tokens.access_token, aad=aad_access)

        # 5. Encrypt or preserve refresh token
        if tokens.refresh_token:
            aad_refresh = build_token_aad(
                user_id=str(state_user_id),
                platform="youtube",
                external_channel_id=channel_id,
                credential_kind="refresh",
            )
            encrypted_refresh: str | None = self.crypto_service.encrypt(
                tokens.refresh_token, aad=aad_refresh
            )
        elif existing_conn and existing_conn.encrypted_refresh_token:
            # Preserve previous refresh token if Google didn't re-issue one
            encrypted_refresh = existing_conn.encrypted_refresh_token
        else:
            encrypted_refresh = None

        expires_at = datetime.now(UTC) + timedelta(seconds=tokens.expires_in)

        # 6. Upsert OAuth connection record
        self.user_repo.upsert_oauth_connection(
            user_id=state_user_id,
            external_channel_id=channel_id,
            granted_scopes=tokens.scope,
            platform="youtube",
            encrypted_access_token=encrypted_access,
            encrypted_refresh_token=encrypted_refresh,
            token_expires_at=expires_at,
            is_active=True,
        )

        # 7. Upsert Channel domain metadata
        self.channel_repo.upsert_channel(
            user_id=state_user_id,
            youtube_channel_id=channel_id,
            title=channel_dto.title,
            uploads_playlist_id=channel_dto.uploads_playlist_id,
            description=channel_dto.description,
            custom_url=channel_dto.custom_url,
            published_at=channel_dto.published_at,
            thumbnail_url=channel_dto.thumbnail_url,
        )

        self.session.commit()
        return channel_dto

    async def get_valid_access_token(
        self,
        user_id: uuid.UUID,
        external_channel_id: str,
    ) -> str:
        """Retrieve a valid, decrypted access token, automatically refreshing if expired."""
        conn = self.user_repo.get_oauth_connection(
            user_id=user_id,
            external_channel_id=external_channel_id,
            platform="youtube",
        )
        if not conn or not conn.is_active:
            raise ResourceNotFoundError(
                f"No active OAuth connection found for channel {external_channel_id}"
            )

        now = datetime.now(UTC)
        is_expired = (
            conn.token_expires_at is None
            or conn.token_expires_at <= now + timedelta(seconds=60)
        )

        if is_expired:
            if not conn.encrypted_refresh_token:
                raise OAuthError(
                    "Access token expired and no refresh token available. "
                    "Re-authorization required."
                )

            aad_refresh = build_token_aad(
                user_id=str(user_id),
                platform="youtube",
                external_channel_id=external_channel_id,
                credential_kind="refresh",
            )
            refresh_token_plain = self.crypto_service.decrypt(
                conn.encrypted_refresh_token, aad=aad_refresh
            )

            new_tokens = await refresh_oauth_token(
                refresh_token=refresh_token_plain,
                client_id=self.settings.youtube_client_id,
                client_secret=self.settings.youtube_client_secret.get_secret_value(),
                http_client=self.http_client,
            )

            aad_access = build_token_aad(
                user_id=str(user_id),
                platform="youtube",
                external_channel_id=external_channel_id,
                credential_kind="access",
            )
            new_encrypted_access = self.crypto_service.encrypt(
                new_tokens.access_token, aad=aad_access
            )

            conn.encrypted_access_token = new_encrypted_access
            conn.token_expires_at = datetime.now(UTC) + timedelta(
                seconds=new_tokens.expires_in
            )

            # If Google rotated the refresh token, update it as well
            if new_tokens.refresh_token and new_tokens.refresh_token != refresh_token_plain:
                conn.encrypted_refresh_token = self.crypto_service.encrypt(
                    new_tokens.refresh_token, aad=aad_refresh
                )

            self.session.commit()
            return new_tokens.access_token

        if not conn.encrypted_access_token:
            raise OAuthError("No access token stored in connection")

        aad_access = build_token_aad(
            user_id=str(user_id),
            platform="youtube",
            external_channel_id=external_channel_id,
            credential_kind="access",
        )
        return self.crypto_service.decrypt(conn.encrypted_access_token, aad=aad_access)

    async def disconnect(
        self,
        user_id: uuid.UUID,
        external_channel_id: str,
    ) -> DisconnectResultDTO:
        """Revoke authorization with Google endpoint and completely delete local stored tokens.

        Explicitly distinguishes between local deactivation and confirmed remote revocation.
        """
        conn = self.user_repo.get_oauth_connection(
            user_id=user_id,
            external_channel_id=external_channel_id,
            platform="youtube",
        )
        if not conn:
            return DisconnectResultDTO(
                channel_id=external_channel_id,
                local_disconnected=True,
                remote_revoked=False,
                details="No existing connection found for this channel",
            )

        # Prioritize revoking refresh token (root grant), fallback to access token
        token_to_revoke: str | None = None
        if conn.encrypted_refresh_token:
            with contextlib.suppress(Exception):
                aad_refresh = build_token_aad(
                    user_id=str(user_id),
                    platform="youtube",
                    external_channel_id=external_channel_id,
                    credential_kind="refresh",
                )
                token_to_revoke = self.crypto_service.decrypt(
                    conn.encrypted_refresh_token, aad=aad_refresh
                )
        elif conn.encrypted_access_token:
            with contextlib.suppress(Exception):
                aad_access = build_token_aad(
                    user_id=str(user_id),
                    platform="youtube",
                    external_channel_id=external_channel_id,
                    credential_kind="access",
                )
                token_to_revoke = self.crypto_service.decrypt(
                    conn.encrypted_access_token, aad=aad_access
                )

        remote_revoked = False
        if token_to_revoke:
            try:
                remote_revoked = await revoke_oauth_token(
                    token=token_to_revoke, http_client=self.http_client
                )
                if remote_revoked:
                    details = "Token successfully revoked at Google OAuth servers"
                else:
                    details = (
                        "Remote revocation request was rejected by Google; "
                        "local credentials purged safely"
                    )
            except Exception:
                remote_revoked = False
                details = (
                    "Transport error communicating with Google revocation endpoint; "
                    "local credentials purged safely"
                )
        else:
            details = (
                "No stored tokens available for remote revocation; "
                "local connection deactivated"
            )

        # Complete local credential purge (tokens are NEVER retained upon disconnect)
        conn.is_active = False
        conn.encrypted_access_token = None
        conn.encrypted_refresh_token = None
        conn.token_expires_at = None
        self.session.commit()

        return DisconnectResultDTO(
            channel_id=external_channel_id,
            local_disconnected=True,
            remote_revoked=remote_revoked,
            details=details,
        )

    def get_connection_status(
        self,
        user_id: uuid.UUID,
        external_channel_id: str,
    ) -> dict[str, Any]:
        """Query connection status without exposing sensitive token material."""
        conn = self.user_repo.get_oauth_connection(
            user_id=user_id,
            external_channel_id=external_channel_id,
            platform="youtube",
        )
        if not conn:
            return {
                "is_connected": False,
                "external_channel_id": external_channel_id,
                "is_active": False,
                "granted_scopes": "",
                "token_expires_at": None,
            }

        return {
            "is_connected": conn.is_active,
            "external_channel_id": conn.external_channel_id,
            "is_active": conn.is_active,
            "granted_scopes": conn.granted_scopes,
            "token_expires_at": conn.token_expires_at,
        }
