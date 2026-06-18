"""Create stock_movements ledger table.

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-18 00:00:00.000000 UTC

M2 Step 2 — the append-only stock movement ledger.

``stock_movements`` is the source of truth for the quantity of any
``exact``-mode lot.  An ``exact`` lot's current quantity equals
``SUM(quantity_delta)`` over all its movements; the denormalised
``stock_instances.quantity`` cache is recomputed from this table after
every write (M2 §4.2 — the "never blind-overwrite" red line).

Table columns and constraints (M2 §3.3):

- ``id``                  — auto-increment PK.
- ``instance_id``         — FK → stock_instances.id, NOT NULL, CASCADE.
- ``type``                — String(20), NOT NULL; validated app-layer.
- ``quantity_delta``      — Numeric(18,6), NOT NULL, signed.
- ``from_location_id``    — FK → locations.id, nullable, SET NULL.
- ``to_location_id``      — FK → locations.id, nullable, SET NULL.
- ``occurred_at``         — DateTime(tz), NOT NULL, default now().
- ``note``                — String(1000), nullable.
- ``reverses_movement_id``— self-FK → stock_movements.id, nullable, SET NULL.
- ``user_id``             — FK → users.id, nullable, SET NULL.
- ``created_at``          — DateTime(tz), NOT NULL, default now().

Indexes created:
1. ``ix_stock_movements_instance_id``        — on (instance_id).
2. ``ix_stock_movements_instance_occurred``  — on (instance_id, occurred_at).
3. ``uq_stock_movements_reversal``           — partial-unique on
   (reverses_movement_id) WHERE reverses_movement_id IS NOT NULL.
   Enforces the "a movement can be reversed at most once" rule at DB level.

Both upgrade and downgrade are fully reversible.
"""

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create the stock_movements table with all columns, FKs, and indexes."""
    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("instance_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(18, 6), nullable=False),
        sa.Column("from_location_id", sa.Integer(), nullable=True),
        sa.Column("to_location_id", sa.Integer(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("note", sa.String(1000), nullable=True),
        # Self-referencing FK — SQLite allows this; declared after all columns.
        sa.Column("reverses_movement_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Primary key.
        sa.PrimaryKeyConstraint("id"),
        # FK → stock_instances.id; CASCADE so a deleted lot removes its ledger.
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["stock_instances.id"],
            name="fk_stock_movements_instance_id",
            ondelete="CASCADE",
        ),
        # FK → locations.id; SET NULL so deleting a location does not destroy history.
        sa.ForeignKeyConstraint(
            ["from_location_id"],
            ["locations.id"],
            name="fk_stock_movements_from_location_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["to_location_id"],
            ["locations.id"],
            name="fk_stock_movements_to_location_id",
            ondelete="SET NULL",
        ),
        # Self-referencing FK; SET NULL so losing the original does not delete the reversal.
        sa.ForeignKeyConstraint(
            ["reverses_movement_id"],
            ["stock_movements.id"],
            name="fk_stock_movements_reverses_movement_id",
            ondelete="SET NULL",
        ),
        # FK → users.id; SET NULL (the acting user may be deleted in a future milestone).
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_stock_movements_user_id",
            ondelete="SET NULL",
        ),
    )

    # 1. Simple index on instance_id for fast lot-history look-ups.
    op.create_index(
        "ix_stock_movements_instance_id",
        "stock_movements",
        ["instance_id"],
    )

    # 2. Composite index on (instance_id, occurred_at) for ordered history reads.
    op.create_index(
        "ix_stock_movements_instance_occurred",
        "stock_movements",
        ["instance_id", "occurred_at"],
    )

    # 3. Partial-unique on reverses_movement_id WHERE NOT NULL.
    #    A movement can be reversed at most once — the DB enforces the constraint
    #    as a backstop in addition to the app-layer check (M2 §2 / §3.3).
    op.create_index(
        "uq_stock_movements_reversal",
        "stock_movements",
        ["reverses_movement_id"],
        unique=True,
        sqlite_where=sa.text("reverses_movement_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop all indexes then drop the stock_movements table."""
    op.drop_index("uq_stock_movements_reversal", table_name="stock_movements")
    op.drop_index("ix_stock_movements_instance_occurred", table_name="stock_movements")
    op.drop_index("ix_stock_movements_instance_id", table_name="stock_movements")
    op.drop_table("stock_movements")
