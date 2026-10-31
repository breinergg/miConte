"""Policy acceptance endpoints.

These routes are intentionally NOT protected by the policy acceptance check —
the user must be able to query document versions and record acceptance before
any other functionality becomes available.

Authentication (CurrentUserDep) is still required so acceptance is bound to
the server-verified identity, never to a client-supplied user ID.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator

from miconte.api.deps import CurrentUserDep, DbSessionDep
from miconte.core.policy import REQUIRED_ACCEPTANCES
from miconte.persistence.repositories.policy_repo import PolicyRepository

router = APIRouter(prefix="/api/v1/policy", tags=["policy"])


class DocumentAcceptanceStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_type: str
    current_version: str
    accepted_version: str | None
    accepted_at: datetime | None
    is_current: bool


class PolicyStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    current_versions: dict[str, str]
    documents: list[DocumentAcceptanceStatus]
    all_current_accepted: bool


class AcceptDocumentRequest(BaseModel):
    document_type: str
    version: str

    @field_validator("document_type")
    @classmethod
    def validate_document_type(cls, v: str) -> str:
        if v not in REQUIRED_ACCEPTANCES:
            raise ValueError(f"Unknown document_type: {v!r}")
        return v

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        if len(v) > 16:
            raise ValueError("version too long")
        return v


class AcceptAllRequest(BaseModel):
    accept_all: bool = False


@router.get(
    "/versions",
    response_model=PolicyStatusResponse,
    summary="Return current document versions and this user's acceptance status",
)
def get_policy_versions(
    current_user: CurrentUserDep,
    session: DbSessionDep,
) -> PolicyStatusResponse:
    """Query which policy documents are required and whether the user has accepted them."""
    repo = PolicyRepository(session)
    documents = []
    all_accepted = True

    for doc_type, current_version in REQUIRED_ACCEPTANCES.items():
        row = repo.get_acceptance(current_user.id, doc_type)
        is_current = row is not None and row.document_version == current_version
        if not is_current:
            all_accepted = False
        documents.append(
            DocumentAcceptanceStatus(
                document_type=doc_type,
                current_version=current_version,
                accepted_version=row.document_version if row else None,
                accepted_at=row.accepted_at if row else None,
                is_current=is_current,
            )
        )

    return PolicyStatusResponse(
        current_versions=dict(REQUIRED_ACCEPTANCES),
        documents=documents,
        all_current_accepted=all_accepted,
    )


@router.post(
    "/accept",
    response_model=PolicyStatusResponse,
    summary="Record explicit acceptance of one or all policy documents",
)
def accept_policy(
    body: AcceptAllRequest | AcceptDocumentRequest,
    current_user: CurrentUserDep,
    session: DbSessionDep,
) -> PolicyStatusResponse:
    """Record the authenticated user's explicit acceptance of policy documents.

    Accepts either a single document (AcceptDocumentRequest) or all current
    documents at once (AcceptAllRequest with accept_all=True).

    The version in the request must match the currently required version —
    accepting a stale version is rejected to prevent clients from gaming the
    acceptance check against outdated documents.
    """
    repo = PolicyRepository(session)
    now = datetime.now(UTC)

    if isinstance(body, AcceptAllRequest):
        if not body.accept_all:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Set accept_all=true to accept all current documents",
            )
        for doc_type, current_version in REQUIRED_ACCEPTANCES.items():
            repo.record_acceptance(
                user_id=current_user.id,
                document_type=doc_type,
                document_version=current_version,
                accepted_at=now,
            )
    else:
        # Single-document acceptance
        expected_version = REQUIRED_ACCEPTANCES.get(body.document_type)
        if expected_version is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown document_type: {body.document_type!r}",
            )
        if body.version != expected_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "VERSION_MISMATCH",
                    "message": (
                        f"Accepting version {body.version!r} for {body.document_type} "
                        f"is not valid; current required version is {expected_version!r}"
                    ),
                },
            )
        repo.record_acceptance(
            user_id=current_user.id,
            document_type=body.document_type,
            document_version=body.version,
            accepted_at=now,
        )

    session.commit()
    return get_policy_versions(current_user=current_user, session=session)
