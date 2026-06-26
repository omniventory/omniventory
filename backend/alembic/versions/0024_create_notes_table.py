"""Create notes table.

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-26 00:00:00.000000 UTC

M5 Step 3 — polymorphic free-text notes.

``notes`` attaches free-text notes to any owner entity identified by
``(model_type, model_id)``.  No hard FK on ``model_id`` (polymorphic);
existence and delete-cascade are enforced in the service layer.

``created_by`` FK → ``users.id`` with ``ondelete=SET NULL`` so that
deleting a user does not remove their notes (the text is still valuable).

``updated_at`` is set to ``now()`` on insert and refreshed on every update
(via SQLAlchemy's ``onupdate=func.now()`` on the ORM model; here in the
migration we just set ``server_default``).

The index on ``(model_type, model_id)`` supports the primary "list notes
for this owner" access pattern.

See M5.md §3.4 for the full schema rationale.

Migration is fully reversible: upgrade creates the table + index,
downgrade drops them.
"""

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create the notes table with index."""
    op.create_table(
        "notes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("model_type", sa.String(32), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey(
                "users.id",
                name="fk_notes_created_by",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Index for "list notes for a given owner" (the primary access pattern).
    op.create_index(
        "ix_notes_owner",
        "notes",
        ["model_type", "model_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the notes table and its index."""
    op.drop_index("ix_notes_owner", table_name="notes")
    op.drop_table("notes")
