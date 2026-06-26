"""Create barcodes table.

Revision ID: 0027
Revises: 0026
Create Date: 2026-06-26 00:00:00.000000 UTC

M5 Step 5 — barcodes attached to item definitions.

``barcodes`` maps a globally-unique scanned code (EAN-13, UPC-A, QR, Code128,
…) to a single item definition.  One definition may have many codes; one code
resolves to exactly one definition (deterministic lookup).

See M5.md §3.6 for the full schema rationale.

Columns
-------
id              Integer PK.
definition_id   FK → item_definitions.id (ondelete=CASCADE): a definition's
                codes go with it when the definition is deleted.
code            String(128) NOT NULL, globally UNIQUE (``uq_barcodes_code``).
                One code → one definition.
symbology       String(16) NOT NULL, default ``'unknown'``.  E.g. ``ean13`` /
                ``upca`` / ``qr`` / ``code128`` / ``internal`` / ``unknown``.
                App-validated; no DB CHECK (roadmap §2.11).
label           String(255) nullable.  Optional human-readable label (e.g.
                "single" vs "case of 24").
created_at      DateTime(tz) server_default now().

Indexes
-------
``uq_barcodes_code``            Unique constraint on code.
``ix_barcodes_definition_id``   Non-unique index on definition_id for fast
                                "list all codes for a definition" queries.

Migration is fully reversible: upgrade creates the table, downgrade drops it.
"""

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create the barcodes table."""
    op.create_table(
        "barcodes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "definition_id",
            sa.Integer(),
            sa.ForeignKey(
                "item_definitions.id",
                name="fk_barcodes_definition_id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("symbology", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("code", name="uq_barcodes_code"),
    )
    op.create_index("ix_barcodes_definition_id", "barcodes", ["definition_id"], unique=False)


def downgrade() -> None:
    """Drop the barcodes table."""
    op.drop_index("ix_barcodes_definition_id", table_name="barcodes")
    op.drop_table("barcodes")
