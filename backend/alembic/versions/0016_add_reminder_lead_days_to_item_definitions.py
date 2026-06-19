"""Add reminder_lead_days to item_definitions.

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-20 00:00:00.000000 UTC

M4 Step 2 — per-item reminder lead-time override.

``item_definitions`` gains one column:

``reminder_lead_days`` Integer, nullable
    Per-item reminder lead override (``≥ 0``, validated app-layer via Pydantic
    ``ge=0`` — no DB CHECK constraint per roadmap §2.11).
    ``NULL`` means "inherit" — the engine falls through to the per-user or
    global default (§4.3 resolution chain).
    Applies to whichever date source this definition's lots carry
    (best_before for perishables, warranty for durables).
    Editing it is non-retroactive (no recompute of existing notifications).

Plain ``op.add_column`` (nullable plain add — no batch table rebuild needed
on SQLite for ADD COLUMN).  Downgrade uses batch mode to drop the column
(SQLite cannot ALTER TABLE DROP COLUMN directly in all versions).

Both upgrade and downgrade are fully reversible.
"""

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Add reminder_lead_days (nullable Integer) to item_definitions."""
    op.add_column(
        "item_definitions",
        sa.Column("reminder_lead_days", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Drop reminder_lead_days from item_definitions (batch mode for SQLite)."""
    # SQLite cannot ALTER TABLE DROP COLUMN directly in all versions;
    # batch mode rebuilds the table to safely remove the column.
    with op.batch_alter_table("item_definitions", schema=None) as batch_op:
        batch_op.drop_column("reminder_lead_days")
