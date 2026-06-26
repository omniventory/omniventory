"""SQLAlchemy model for the Note table (M5 §3.4).

``Note`` attaches a free-text body to any owner entity identified by the
polymorphic pair ``(model_type, model_id)``.  No hard FK on ``model_id`` —
the owner is polymorphic (item_definition, stock_instance, location).
Allowed types are validated by the service layer via the ``OWNER_TYPES``
registry.

``created_by`` → ``users.id`` with ``ondelete=SET NULL``: deleting a user
nulls the author field but keeps the note text (the content is still valuable).

``updated_at`` uses ``onupdate=func.now()`` so every ORM flush that changes
the row also refreshes the timestamp.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Note(Base):
    """A free-text note attached to a polymorphic owner.

    Columns
    -------
    id          Auto-increment surrogate PK.
    model_type  Owner type string: ``item_definition`` / ``stock_instance`` /
                ``location`` (validated app-layer; no DB CHECK).
    model_id    Owner PK (no hard FK — polymorphic).
    body        Free text (Text; cannot be empty — checked by service/schema).
    created_by  FK → users.id (SET NULL on user delete).  Nullable.
    created_at  Row-creation timestamp (UTC, set by DB on insert).
    updated_at  Last-update timestamp (UTC); refreshed on every ORM flush
                that modifies the row via ``onupdate=func.now()``.
    """

    __tablename__ = "notes"

    __table_args__ = (
        # Fast lookup of all notes for a given owner.
        Index("ix_notes_owner", "model_type", "model_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_type: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", name="fk_notes_created_by", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"Note(id={self.id!r}, model_type={self.model_type!r}, "
            f"model_id={self.model_id!r}, created_by={self.created_by!r})"
        )
