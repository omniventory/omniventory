"""SQLAlchemy model for the Barcode table (M5 §3.6).

``Barcode`` maps a globally-unique scanned code to a single item definition.
One definition may carry many codes; a code resolves to exactly one definition
(deterministic lookup via the UNIQUE constraint on ``code``).

``definition_id`` → ``item_definitions.id`` with ``ondelete=CASCADE``: deleting
a definition automatically deletes all its bound barcodes at the DB level.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Barcode(Base):
    """A scanned code bound to an item definition.

    Columns
    -------
    id              Auto-increment surrogate PK.
    definition_id   FK → item_definitions.id (CASCADE on delete).
    code            Globally unique code string (String(128)).  The UNIQUE
                    constraint ``uq_barcodes_code`` enforces one-code →
                    one-definition globally.
    symbology       Barcode type (String(16)); default ``'unknown'``.
                    Validated app-layer; no DB CHECK (roadmap §2.11).
    label           Optional human-readable label (String(255), nullable).
    created_at      Row-creation timestamp (UTC, set by DB on insert).
    """

    __tablename__ = "barcodes"

    __table_args__ = (
        # One code → one definition globally.
        UniqueConstraint("code", name="uq_barcodes_code"),
        # Fast "list all codes for a definition" index.
        Index("ix_barcodes_definition_id", "definition_id", unique=False),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    definition_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "item_definitions.id",
            name="fk_barcodes_definition_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    symbology: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    label: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"Barcode(id={self.id!r}, definition_id={self.definition_id!r}, "
            f"code={self.code!r}, symbology={self.symbology!r})"
        )
