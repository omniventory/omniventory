"""Create app_config table for server-managed key/value configuration.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-15 00:00:00.000000 UTC

This migration adds the ``app_config`` table used to persist server-managed
settings that must survive container restarts (M0 rework):

``app_config``
    Key/value store with a string PK (``key``) and a text ``value`` column.
    Used initially to persist the auto-generated ``secret_key`` so that
    sessions remain valid across restarts when no ``SECRET_KEY`` env var is
    set.  Kept separate from ``Household.settings`` (user config) so
    server-managed secrets never appear in user-facing APIs.

The migration is fully reversible: ``downgrade`` drops the table.
"""

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create the app_config table."""
    op.create_table(
        "app_config",
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", sa.String(4096), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    """Drop the app_config table."""
    op.drop_table("app_config")
