"""Create households table and ensure singleton row exists.

Revision ID: 0001
Revises:
Create Date: 2026-06-15 00:00:00.000000 UTC

This migration:
1. Creates the ``households`` table with a CHECK constraint that enforces the
   singleton invariant at the DB level: ``CHECK (id = 1)``.
2. Inserts the singleton row (id=1) with sane defaults so the row is always
   present after ``alembic upgrade head`` on a fresh DB.

Upgrade is idempotent with respect to the row: if the row already exists the
INSERT is a no-op.  The seed uses SQLite-specific ``INSERT OR IGNORE`` syntax.
M0 is SQLite-only; portability to Postgres (``ON CONFLICT DO NOTHING``) is
deferred to when Postgres support is actually added.

Downgrade removes the row and drops the table (fully reversible).
"""

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create the households table and seed the singleton row."""
    op.create_table(
        "households",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, server_default="My Household"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("settings", sa.Text(), nullable=True),
        # DB-level singleton guard: only id = 1 is permitted.
        sa.CheckConstraint("id = 1", name="ck_households_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Seed the singleton row.  Uses INSERT OR IGNORE so that re-running the
    # migration (e.g. in tests) does not fail if the row already exists.
    op.execute(
        sa.text(
            "INSERT OR IGNORE INTO households (id, name, currency, timezone) "
            "VALUES (1, 'My Household', 'USD', 'UTC')"
        )
    )


def downgrade() -> None:
    """Remove the singleton row and drop the households table."""
    op.execute(sa.text("DELETE FROM households WHERE id = 1"))
    op.drop_table("households")
