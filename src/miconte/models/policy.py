"""Policy acceptance domain model — records each user's explicit consent to documents."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from miconte.persistence.base import Base


class PolicyAcceptance(Base):
    """Records a user's explicit acceptance of a versioned policy document.

    One row per (user, document_type). When a document version changes, the row
    is updated in-place so that the most recent acceptance is always queryable
    in O(1) without a history scan. The unique constraint on (user_id, document_type)
    enforces one-record-per-document semantics.
    """

    __tablename__ = "policy_acceptances"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "document_type",
            name="uq_policy_acceptance_user_document",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="'privacy_policy' or 'terms_of_use'",
    )
    document_version: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="Version string from miconte.core.policy, e.g. '1.0'",
    )
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    user: Mapped["User"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "User",
        back_populates="policy_acceptances",
    )
