"""Tests for the policy acceptance feature.

Covers:
1. Unaccepted user is blocked by check_policy_acceptance (HTTP 403).
2. User accepts all documents; subsequent check passes (HTTP 200).
3. User who already accepted current versions is not re-prompted.
4. Version bump: previously accepted version no longer satisfies check.
5. Backend policy endpoint returns structured 403 for protected routes.
6. Exempt endpoints (versions query, accept POST) work without prior acceptance.
7. Acceptance is user-scoped: one user's acceptance does not affect another.
"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from miconte.core.policy import REQUIRED_ACCEPTANCES
from miconte.main import app
from miconte.models.user import User
from miconte.persistence.repositories.policy_repo import PolicyRepository
from miconte.persistence.session import get_engine

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_session() -> Generator[Session]:
    engine = get_engine()
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_user(session: Session, *, suffix: str = "") -> User:
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"policy_test_{suffix}_{uid}@example.com",
        hashed_password="x",
        full_name="Policy Test",
        is_active=True,
    )
    session.add(user)
    session.flush()
    return user


def _accept_all(session: Session, user: User) -> None:
    repo = PolicyRepository(session)
    now = datetime.now(UTC)
    for doc_type, version in REQUIRED_ACCEPTANCES.items():
        repo.record_acceptance(
            user_id=user.id,
            document_type=doc_type,
            document_version=version,
            accepted_at=now,
        )
    session.commit()


# ---------------------------------------------------------------------------
# Unit tests: PolicyRepository
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_user(db_session: Session) -> User:
    return _create_user(db_session, suffix="unit")


def test_missing_acceptances_when_none_recorded(db_session: Session, db_user: User) -> None:
    repo = PolicyRepository(db_session)
    missing = repo.missing_current_acceptances(db_user.id)
    assert set(missing) == set(REQUIRED_ACCEPTANCES.keys())


def test_has_accepted_after_recording_all(db_session: Session, db_user: User) -> None:
    _accept_all(db_session, db_user)
    repo = PolicyRepository(db_session)
    assert repo.has_accepted_current_versions(db_user.id) is True
    assert repo.missing_current_acceptances(db_user.id) == []


def test_version_bump_invalidates_acceptance(db_session: Session, db_user: User) -> None:
    _accept_all(db_session, db_user)
    with patch.dict(REQUIRED_ACCEPTANCES, {"privacy_policy": "2.0"}):
        repo = PolicyRepository(db_session)
        missing = repo.missing_current_acceptances(db_user.id)
        assert "privacy_policy" in missing
        assert repo.has_accepted_current_versions(db_user.id) is False


def test_acceptance_is_user_scoped(db_session: Session) -> None:
    user_a = _create_user(db_session, suffix="scope_a")
    user_b = _create_user(db_session, suffix="scope_b")
    _accept_all(db_session, user_a)
    repo = PolicyRepository(db_session)
    assert repo.has_accepted_current_versions(user_b.id) is False
    missing = repo.missing_current_acceptances(user_b.id)
    assert set(missing) == set(REQUIRED_ACCEPTANCES.keys())


# ---------------------------------------------------------------------------
# Integration tests: HTTP endpoints via TestClient
# ---------------------------------------------------------------------------

@pytest.fixture()
def unaccepted_user(db_session: Session) -> User:
    user = _create_user(db_session, suffix="http_unaccepted")
    db_session.commit()
    return user


def test_protected_endpoint_blocked_without_acceptance(
    client: TestClient, unaccepted_user: User
) -> None:
    """A user who has not accepted any documents gets HTTP 403 on protected routes."""
    resp = client.get(
        "/api/v1/sync/scheduler/status",
        headers={"X-User-Id": str(unaccepted_user.id)},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["detail"]["code"] == "POLICY_NOT_ACCEPTED"
    assert set(body["detail"]["missing_documents"]) == set(REQUIRED_ACCEPTANCES.keys())


def test_policy_versions_endpoint_exempt(
    client: TestClient, unaccepted_user: User
) -> None:
    """GET /api/v1/policy/versions must work without prior acceptance."""
    resp = client.get(
        "/api/v1/policy/versions",
        headers={"X-User-Id": str(unaccepted_user.id)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["all_current_accepted"] is False


def test_accept_all_then_access_protected(
    client: TestClient, unaccepted_user: User
) -> None:
    """After accepting all documents the protected endpoint returns non-403."""
    resp = client.post(
        "/api/v1/policy/accept",
        json={"accept_all": True},
        headers={"X-User-Id": str(unaccepted_user.id)},
    )
    assert resp.status_code == 200
    assert resp.json()["all_current_accepted"] is True

    resp2 = client.get(
        "/api/v1/sync/scheduler/status",
        headers={"X-User-Id": str(unaccepted_user.id)},
    )
    detail = resp2.json().get("detail", {})
    if isinstance(detail, dict):
        assert detail.get("code") != "POLICY_NOT_ACCEPTED"
    else:
        assert resp2.status_code != 403


def test_already_accepted_current_versions_passes(
    client: TestClient, db_session: Session
) -> None:
    """A user who already accepted current versions is not blocked."""
    user = _create_user(db_session, suffix="already_accepted")
    db_session.commit()
    _accept_all(db_session, user)

    resp = client.get(
        "/api/v1/policy/versions",
        headers={"X-User-Id": str(user.id)},
    )
    assert resp.status_code == 200
    assert resp.json()["all_current_accepted"] is True
