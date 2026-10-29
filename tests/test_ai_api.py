"""Integration tests for the Phase 9 AI interpretation API endpoint.

Uses the real PostgreSQL test database so that channel ownership checks are
exercised against actual rows — consistent with test_analytics_api.py.

Pattern (same as test_analytics_api.py):
  - db_session fixture flushes but does NOT commit.
  - Tests that need TestClient to see the data call db_session.commit() explicitly.
  - Unique UUIDs in emails avoid inter-test conflicts.

Critical security behaviours verified:
  - Compliance gate: endpoint blocks ALL content when analytics_real_data_enabled=False.
  - No bypass via real_data field in body (field removed from schema; extra fields ignored).
  - LLM disabled / unavailable → HTTP 200 when gate is open.
  - Ownership / IDOR: channel must belong to authenticated user.
  - Invalid UUID → 422.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from miconte.ai._models import InterpretationResponse, LLMStatus
from miconte.api.ai import get_ai_service
from miconte.core.config import Settings, get_settings
from miconte.main import app
from miconte.models.channel import Channel
from miconte.models.user import User
from miconte.persistence.session import get_engine

_GATE_OPEN_SETTINGS = Settings(analytics_real_data_enabled=True, environment="testing")


# ─── Stub AI service ──────────────────────────────────────────────────────────

class _StubAIService:
    def __init__(self, response: InterpretationResponse) -> None:
        self._response = response

    async def interpret_channel_analytics(self, **kwargs: object) -> InterpretationResponse:
        return self._response


def _disabled_response() -> InterpretationResponse:
    return InterpretationResponse(
        status=LLMStatus.disabled, summary=None, provider="none", degraded=True
    )


def _ok_response() -> InterpretationResponse:
    return InterpretationResponse(
        status=LLMStatus.ok,
        summary="Se observa una asociación positiva entre la duración y el APV.",
        provider="ollama",
        model="llama3.2",
        degraded=False,
    )


def _unavailable_response() -> InterpretationResponse:
    return InterpretationResponse(
        status=LLMStatus.unavailable, summary=None, provider="ollama", degraded=True
    )


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def db_session() -> Generator[Session]:
    engine = get_engine()
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture
def test_user(db_session: Session) -> User:
    user = User(
        email=f"ai-test-{uuid.uuid4()}@example.com",
        hashed_password="$2b$12$placeholder_test_hash",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def other_user(db_session: Session) -> User:
    user = User(
        email=f"ai-other-{uuid.uuid4()}@example.com",
        hashed_password="$2b$12$placeholder_other_hash",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def test_channel(db_session: Session, test_user: User) -> Channel:
    channel = Channel(
        user_id=test_user.id,
        youtube_channel_id=f"UC_ai_{uuid.uuid4().hex[:8]}",
        title="Test AI Channel",
        uploads_playlist_id=f"UU_ai_{uuid.uuid4().hex[:8]}",
    )
    db_session.add(channel)
    db_session.flush()
    return channel


@pytest.fixture(autouse=True)
def _cleanup_overrides() -> Generator[None]:
    """Ensure dependency_overrides are removed after each test."""
    yield
    app.dependency_overrides.pop(get_ai_service, None)
    app.dependency_overrides.pop(get_settings, None)


def _headers(user: User) -> dict[str, str]:
    return {"X-User-Id": str(user.id)}


def _client_gate_closed() -> TestClient:
    """No overrides — analytics_real_data_enabled=False (default)."""
    return TestClient(app, raise_server_exceptions=True)


def _client_gate_open(ai_response: InterpretationResponse) -> TestClient:
    """Gate open + stubbed AI service."""
    app.dependency_overrides[get_settings] = lambda: _GATE_OPEN_SETTINGS
    app.dependency_overrides[get_ai_service] = lambda: _StubAIService(ai_response)
    return TestClient(app, raise_server_exceptions=True)


def _base_payload(channel_title: str = "Canal Sintético") -> dict:  # type: ignore[type-arg]
    return {
        "channel_title": channel_title,
        "period_label": "2026-09-27 — 2026-10-27",
        "metrics": [
            {
                "label": "Visualizaciones diarias",
                "value": 500.0,
                "unit": "views/day",
                "n": 30,
                "ci_95": [440.0, 560.0],
                "limitations": [],
            }
        ],
        "recommendations": [
            {
                "rule_code": "CTR_BELOW_BASELINE",
                "priority": "high",
                "description": "El CTR se encuentra por debajo de la mediana.",
                "metrics_evidence": {},
            }
        ],
        # real_data intentionally absent — removed from schema.
    }


# ─── Compliance gate ──────────────────────────────────────────────────────────

class TestComplianceGate:
    """The endpoint must block ALL content from reaching any LLM adapter
    while analytics_real_data_enabled=False (the default)."""

    def test_gate_closed_blocks_before_llm_is_called(
        self, test_user: User, test_channel: Channel, db_session: Session
    ) -> None:
        """With default settings the endpoint returns unavailable without calling LLM."""
        db_session.commit()
        client = _client_gate_closed()
        resp = client.post(
            f"/api/v1/channels/{test_channel.id}/ai/interpret",
            json=_base_payload(),
            headers=_headers(test_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ai_status"] == "unavailable"
        assert data["degraded"] is True
        assert "MICONTE_ANALYTICS_REAL_DATA_ENABLED" in data["note"]

    def test_gate_closed_real_data_field_in_body_does_not_bypass(
        self, test_user: User, test_channel: Channel, db_session: Session
    ) -> None:
        """Sending real_data=False (or True) in body does not change gate outcome."""
        db_session.commit()
        client = _client_gate_closed()
        for injected_value in (False, True):
            payload = _base_payload()
            payload["real_data"] = injected_value  # type: ignore[assignment]
            resp = client.post(
                f"/api/v1/channels/{test_channel.id}/ai/interpret",
                json=payload,
                headers=_headers(test_user),
            )
            assert resp.status_code == 200
            assert resp.json()["ai_status"] == "unavailable", (
                f"Gate bypassed with real_data={injected_value}"
            )


# ─── AI status behaviour (gate open) ─────────────────────────────────────────

class TestAIStatusBehaviourGateOpen:
    """When analytics_real_data_enabled=True the LLM adapter path is exercised."""

    def test_disabled_llm_returns_200(
        self, test_user: User, test_channel: Channel, db_session: Session
    ) -> None:
        db_session.commit()
        client = _client_gate_open(_disabled_response())
        resp = client.post(
            f"/api/v1/channels/{test_channel.id}/ai/interpret",
            json=_base_payload(),
            headers=_headers(test_user),
        )
        assert resp.status_code == 200
        assert resp.json()["ai_status"] == "disabled"

    def test_ok_llm_returns_200_with_summary(
        self, test_user: User, test_channel: Channel, db_session: Session
    ) -> None:
        db_session.commit()
        client = _client_gate_open(_ok_response())
        resp = client.post(
            f"/api/v1/channels/{test_channel.id}/ai/interpret",
            json=_base_payload(),
            headers=_headers(test_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ai_status"] == "ok"
        assert "asociación" in (data["ai_summary"] or "")
        assert data["degraded"] is False

    def test_unavailable_llm_returns_200_not_5xx(
        self, test_user: User, test_channel: Channel, db_session: Session
    ) -> None:
        db_session.commit()
        client = _client_gate_open(_unavailable_response())
        resp = client.post(
            f"/api/v1/channels/{test_channel.id}/ai/interpret",
            json=_base_payload(),
            headers=_headers(test_user),
        )
        assert resp.status_code == 200
        assert resp.json()["ai_status"] == "unavailable"

    def test_channel_id_echoed_in_response(
        self, test_user: User, test_channel: Channel, db_session: Session
    ) -> None:
        db_session.commit()
        client = _client_gate_open(_disabled_response())
        resp = client.post(
            f"/api/v1/channels/{test_channel.id}/ai/interpret",
            json=_base_payload(),
            headers=_headers(test_user),
        )
        assert resp.status_code == 200
        assert resp.json()["channel_id"] == str(test_channel.id)

    def test_invalid_channel_uuid_returns_422(
        self, test_user: User, db_session: Session
    ) -> None:
        db_session.commit()
        client = _client_gate_open(_disabled_response())
        resp = client.post(
            "/api/v1/channels/not-a-uuid/ai/interpret",
            json=_base_payload(),
            headers=_headers(test_user),
        )
        assert resp.status_code == 422


# ─── Ownership / IDOR ─────────────────────────────────────────────────────────

class TestOwnershipEnforcement:
    def test_owner_can_access_channel(
        self, test_user: User, test_channel: Channel, db_session: Session
    ) -> None:
        db_session.commit()
        # Gate open so we reach the ownership check (gate closed returns early).
        client = _client_gate_open(_disabled_response())
        resp = client.post(
            f"/api/v1/channels/{test_channel.id}/ai/interpret",
            json=_base_payload(),
            headers=_headers(test_user),
        )
        assert resp.status_code == 200

    def test_other_user_cannot_access_channel(
        self,
        other_user: User,
        test_channel: Channel,
        db_session: Session,
    ) -> None:
        """A different authenticated user must not be able to use another user's channel_id."""
        db_session.commit()
        client = _client_gate_open(_disabled_response())
        resp = client.post(
            f"/api/v1/channels/{test_channel.id}/ai/interpret",
            json=_base_payload(),
            headers=_headers(other_user),
        )
        assert resp.status_code == 404

    def test_nonexistent_channel_returns_404(
        self, test_user: User, db_session: Session
    ) -> None:
        db_session.commit()
        client = _client_gate_open(_disabled_response())
        resp = client.post(
            f"/api/v1/channels/{uuid.uuid4()}/ai/interpret",
            json=_base_payload(),
            headers=_headers(test_user),
        )
        assert resp.status_code == 404
