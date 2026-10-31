"""add_policy_acceptances

Adds:
- policy_acceptances table — records explicit user acceptance of privacy policy
  and terms of use documents, keyed by (user_id, document_type) with a unique
  constraint so acceptance is stored as a single row per document, upserted on
  version change.

Revision ID: e1f2a3b4c5d6
Revises: a1b2c3d4e5f6
Create Date: 2026-10-31 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "policy_acceptances",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column("document_version", sa.String(length=16), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_policy_acceptances_user_id",
        "policy_acceptances",
        ["user_id"],
    )
    op.create_unique_constraint(
        "uq_policy_acceptance_user_document",
        "policy_acceptances",
        ["user_id", "document_type"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uq_policy_acceptance_user_document",
        "policy_acceptances",
        type_="unique",
    )
    op.drop_index("ix_policy_acceptances_user_id", table_name="policy_acceptances")
    op.drop_table("policy_acceptances")
