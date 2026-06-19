"""Create notifications table.

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-20 00:00:00.000000 UTC

M4 Step 3 — in-app notification inbox and dedup ledger.

``notifications`` is the unified inbox + idempotency ledger + low-stock episode
record.  Every in-app notification (best_before, warranty, low_stock) lands here
as one row; the unique ``(user_id, dedup_key)`` pair makes re-running the engine
idempotent.

See M4.md §3.2 and §3.3 for the full schema rationale.  Low-stock episode
columns (``episode_started_on``, ``offset_days``, ``resolved_at``) are created
here so the schema is stable for Step 4, even though Step 3 does not write them.

Migration is fully reversible: upgrade creates the table + indexes, downgrade
drops the table.
"""

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create the notifications table with all indexes."""
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_notifications_user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("subject_type", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("dedup_key", sa.String(255), nullable=False),
        sa.Column("message_code", sa.String(64), nullable=False),
        sa.Column("params", sa.Text(), nullable=True),
        # Low-stock episode columns (written by Step 4; NULL for date sources)
        sa.Column("episode_started_on", sa.Date(), nullable=True),
        sa.Column("offset_days", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        # Read-state
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        # Creation timestamp
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Unique idempotency constraint: one notification per (user, dedup_key)
    op.create_index(
        "uq_notifications_user_dedup",
        "notifications",
        ["user_id", "dedup_key"],
        unique=True,
    )

    # Non-unique index to make unread-count / inbox queries cheap
    op.create_index(
        "ix_notifications_user_read_at",
        "notifications",
        ["user_id", "read_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the notifications table and its indexes."""
    op.drop_index("ix_notifications_user_read_at", table_name="notifications")
    op.drop_index("uq_notifications_user_dedup", table_name="notifications")
    op.drop_table("notifications")
