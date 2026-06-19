"""Add reminder lead-day overrides to users table.

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-20 00:00:00.000000 UTC

M4 Step 2 — per-user reminder lead-time overrides.

``users`` gains two columns:

``reminder_best_before_lead_days`` Integer, nullable
    Per-user override for the best-before lead time (``≥ 0``, validated
    app-layer via Pydantic ``ge=0`` — no DB CHECK constraint per roadmap
    §2.11).  ``NULL`` means "inherit global default" (§4.3 resolution chain).

``reminder_warranty_lead_days`` Integer, nullable
    Per-user override for the warranty-expiry lead time (``≥ 0``, same rules).
    ``NULL`` means "inherit global default".

Both columns mirror the existing ``preferred_language`` nullable lifecycle:
no server default, existing rows stay NULL (correct — "inherit" = no
override configured), no DB CHECK constraint.

Plain ``op.add_column`` for upgrade (nullable ADD COLUMN is safe on SQLite
without batch mode).  Downgrade uses batch mode (SQLite cannot ALTER TABLE
DROP COLUMN directly in all versions).

Both upgrade and downgrade are fully reversible.
"""

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Add reminder_best_before_lead_days and reminder_warranty_lead_days to users."""
    op.add_column(
        "users",
        sa.Column("reminder_best_before_lead_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("reminder_warranty_lead_days", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Drop the two reminder lead-day columns from users (batch mode for SQLite)."""
    # SQLite cannot ALTER TABLE DROP COLUMN directly in all versions;
    # batch mode rebuilds the table to safely remove the columns.
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("reminder_warranty_lead_days")
        batch_op.drop_column("reminder_best_before_lead_days")
