"""Create settings table.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-20 00:00:00.000000 UTC

M4 Step 1 — user-facing KV configuration store.

Creates the ``settings`` table which holds user-editable configuration
(reminder lead times, channel settings) as dot-namespaced key/value pairs.

Design decisions (M4 §2 / §3.1):
- DISTINCT from ``app_config`` (server-managed secrets) and
  ``household.settings`` (JSON blob) — this is the user-facing surface.
- Only OVERRIDDEN keys are stored; unset keys return code-defined defaults
  via ``SettingsService``.
- ``value`` is Text (not String(N)) to accommodate JSON arrays / long URLs.
- ``updated_at`` has a server-side default (``now()``) so it is always
  populated on INSERT.  UPDATE statements issued by ``Session.merge``
  include an explicit ``now()`` via SQLAlchemy's ``onupdate=func.now()``
  on the model column, satisfying the M4 §3.1 "refreshed on upsert"
  requirement.  No DB-level trigger or ``server_onupdate`` is needed
  because SQLAlchemy emits the value in the UPDATE clause itself.

Both upgrade and downgrade are fully reversible.
"""

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create the settings table."""
    op.create_table(
        "settings",
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    """Drop the settings table."""
    op.drop_table("settings")
