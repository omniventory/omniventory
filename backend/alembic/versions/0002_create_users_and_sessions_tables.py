"""Create users and sessions tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-15 00:00:00.000000 UTC

This migration adds two tables required for the session-cookie auth skeleton
(M0 Step 4):

``users``
    Stores user accounts.  ``email`` has a UNIQUE constraint.  Only one admin
    user is expected in M0; multi-user arrives in M6.

``sessions``
    Server-side session store.  ``id`` is the opaque random token that travels
    in the HttpOnly cookie.  ``user_id`` references ``users.id`` with
    ``ON DELETE CASCADE`` so sessions are automatically removed when a user is
    deleted.  ``expires_at`` is checked in the application layer.

Both tables are fully reversible (``downgrade`` drops them in dependency
order: sessions first, then users).
"""

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create users and sessions tables."""
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(1024), nullable=False),
        sa.Column("role", sa.String(64), nullable=False, server_default="admin"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_sessions_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])


def downgrade() -> None:
    """Drop sessions and users tables (in dependency order)."""
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
