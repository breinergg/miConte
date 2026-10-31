"""Policy acceptance repository — stores and queries user consent records."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from miconte.core.policy import REQUIRED_ACCEPTANCES
from miconte.models.policy import PolicyAcceptance


class PolicyRepository:
    """Repository managing PolicyAcceptance records."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record_acceptance(
        self,
        *,
        user_id: uuid.UUID,
        document_type: str,
        document_version: str,
        accepted_at: datetime | None = None,
    ) -> PolicyAcceptance:
        """Upsert acceptance for (user_id, document_type).

        If a row exists for this user+document_type, updates its version and timestamp
        so the constraint is satisfied and history is not duplicated.
        """
        stmt = select(PolicyAcceptance).where(
            PolicyAcceptance.user_id == user_id,
            PolicyAcceptance.document_type == document_type,
        )
        existing = self.session.execute(stmt).scalar_one_or_none()
        now = accepted_at or datetime.now(UTC)

        if existing is None:
            row = PolicyAcceptance(
                user_id=user_id,
                document_type=document_type,
                document_version=document_version,
                accepted_at=now,
            )
            self.session.add(row)
        else:
            existing.document_version = document_version
            existing.accepted_at = now
            row = existing

        self.session.flush()
        return row

    def get_acceptance(
        self,
        user_id: uuid.UUID,
        document_type: str,
    ) -> PolicyAcceptance | None:
        stmt = select(PolicyAcceptance).where(
            PolicyAcceptance.user_id == user_id,
            PolicyAcceptance.document_type == document_type,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_all_acceptances(self, user_id: uuid.UUID) -> list[PolicyAcceptance]:
        stmt = select(PolicyAcceptance).where(PolicyAcceptance.user_id == user_id)
        return list(self.session.execute(stmt).scalars().all())

    def has_accepted_current_versions(self, user_id: uuid.UUID) -> bool:
        """Return True iff the user has accepted ALL documents at their current versions."""
        for doc_type, current_version in REQUIRED_ACCEPTANCES.items():
            row = self.get_acceptance(user_id, doc_type)
            if row is None or row.document_version != current_version:
                return False
        return True

    def missing_current_acceptances(self, user_id: uuid.UUID) -> list[str]:
        """Return list of document_type strings whose current version is not yet accepted."""
        missing = []
        for doc_type, current_version in REQUIRED_ACCEPTANCES.items():
            row = self.get_acceptance(user_id, doc_type)
            if row is None or row.document_version != current_version:
                missing.append(doc_type)
        return missing
