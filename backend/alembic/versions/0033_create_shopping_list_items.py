"""Create shopping_list_items table.

Revision ID: 0033
Revises: 0032
Create Date: 2026-06-28 00:00:00.000000 UTC

M7 Step 1 — household-shared shopping list (auto + manual rows).

``shopping_list_items`` is the persisted shopping list.  Each row is either
``auto`` (materialised from the low-stock signal by reconcile_auto_items(),
added in Step 2) or ``manual`` (user-entered, free-text or definition-linked).

Columns
-------
id               Integer PK.
source           String(16) NOT NULL; ``auto`` / ``manual``.  App-validated,
                 no DB CHECK (roadmap §2.11).
definition_id    FK → item_definitions.id (ondelete=CASCADE); nullable for
                 free-text manual items.
name             String(255) nullable; free-text label for definition-less
                 manual items.  For definition-linked rows the display name
                 is read live from the definition.
desired_quantity Numeric(18,6) nullable — how much to buy.
unit             String(32) nullable; unit label for definition-less manual
                 items.
note             String(1000) nullable; free-text note.
purchased_at     DateTime(tz) nullable; check-off state — NULL = open/
                 unchecked; set = purchased/checked.
created_by       FK → users.id (ondelete=SET NULL); nullable.
created_at       DateTime(tz) NOT NULL; server_default=now().
updated_at       DateTime(tz) NOT NULL; server_default=now(); refreshed on
                 update via ORM onupdate.

Indexes
-------
``uq_shopping_list_one_auto_per_def``
    Partial unique on ``(definition_id) WHERE source='auto'``: at most one
    auto row per definition, in any purchased state (open or checked).  The
    state-independent scope means a check-off / uncheck round-trip can never
    create a colliding second auto row.  Uses ``sqlite_where`` like the M2
    serial partial-unique index (``uq_stock_instances_definition_serial``).
``ix_shopping_list_items_purchased_at``
    Non-unique on ``(purchased_at)`` for the open/done split query.

Migration is fully reversible: upgrade creates the table and indexes;
downgrade drops the indexes then the table.
"""

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create the shopping_list_items table and its indexes."""
    op.create_table(
        "shopping_list_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column(
            "definition_id",
            sa.Integer(),
            sa.ForeignKey(
                "item_definitions.id",
                name="fk_shopping_list_items_definition_id",
                ondelete="CASCADE",
            ),
            nullable=True,
        ),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("desired_quantity", sa.Numeric(18, 6), nullable=True),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("note", sa.String(1000), nullable=True),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey(
                "users.id",
                name="fk_shopping_list_items_created_by",
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
    # Partial unique: at most one auto row per definition (state-independent).
    # sqlite_where mirrors the idiom from migration 0008 for stock_instances.
    op.create_index(
        "uq_shopping_list_one_auto_per_def",
        "shopping_list_items",
        ["definition_id"],
        unique=True,
        sqlite_where=sa.text("source='auto'"),
    )
    # Non-unique: open/done split queries.
    op.create_index(
        "ix_shopping_list_items_purchased_at",
        "shopping_list_items",
        ["purchased_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the shopping_list_items table and its indexes."""
    op.drop_index("ix_shopping_list_items_purchased_at", table_name="shopping_list_items")
    op.drop_index("uq_shopping_list_one_auto_per_def", table_name="shopping_list_items")
    op.drop_table("shopping_list_items")
