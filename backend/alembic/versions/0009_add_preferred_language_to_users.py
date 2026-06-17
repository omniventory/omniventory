"""Add preferred_language column to users table.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-17 00:00:00.000000 UTC

M1.5 Step 2 — per-user preferred language preference.

``users.preferred_language`` is a nullable ``String(16)`` column.
- NULL means "never explicitly chosen" → the frontend falls through to its own
  resolution chain (localStorage → navigator detect → 'en').
- A concrete value (e.g. ``'en'`` or ``'zh'``) is authoritative and follows
  the account across devices.
- No server default — existing rows stay NULL (correct behaviour).
- No DB CHECK constraint — the supported set is enforced at the app layer
  (``app/core/languages.py``) per roadmap §2.11.

ADD COLUMN with a nullable column requires **no** batch-rebuild on SQLite.
Downgrade drops the column; SQLite cannot ALTER TABLE DROP COLUMN directly,
so we use batch mode for the drop (rebuilds the table transparently).
"""

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Add preferred_language (nullable String(16)) to users."""
    op.add_column("users", sa.Column("preferred_language", sa.String(16), nullable=True))


def downgrade() -> None:
    """Drop preferred_language from users (batch mode — SQLite cannot ALTER TABLE DROP COLUMN)."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("preferred_language")
