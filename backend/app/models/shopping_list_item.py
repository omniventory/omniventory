"""SQLAlchemy model for the ShoppingListItem table (M7 §3.1).

A ``shopping_list_item`` is one row in the household-shared shopping list.
It can be either:
- ``auto``   — materialised from the low-stock signal by reconcile_auto_items()
               (added in Step 2).
- ``manual`` — user-entered (free-text or linked to an item definition).

Design notes
------------
- ``source`` is validated app-layer against ``SHOPPING_LIST_SOURCES``; no DB
  CHECK constraint (roadmap §2.11).
- ``definition_id`` FK → ``item_definitions.id`` with ``ondelete=CASCADE``:
  deleting a definition removes all its shopping-list rows.  Nullable — free-text
  manual items carry no definition.
- ``name`` is the free-text label for definition-less manual rows.  For
  definition-linked rows the display name is read **live** from the definition
  (kept fresh, not snapshotted); this field is NULL or unused for those rows.
  A row must have ``definition_id`` **or** ``name`` (app-layer cross-field check).
- ``desired_quantity`` is Numeric(18,6) — never float (roadmap §2.9).
- ``purchased_at`` is the check-off state: NULL = open/unchecked; set = checked.
- ``created_by`` FK → ``users.id`` with ``ondelete=SET NULL``: deleting a user
  NULLs the author field but keeps the row.
- **Partial unique index** ``uq_shopping_list_one_auto_per_def`` on
  ``(definition_id) WHERE source='auto'``: at most one auto row per definition,
  in *any* purchased state (open or checked).  Making it state-independent means
  a check-off / uncheck round-trip can never produce a colliding second auto row.
  Uses the same ``sqlite_where`` idiom as the M2 serial partial-unique index in
  ``app/models/stock_instance.py``.
- Non-unique index on ``(purchased_at)`` for efficient open/done split queries.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.item_definition import ItemDefinition
    from app.models.user import User

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ShoppingListItem(Base):
    """A row in the household-shared shopping list (auto or manual source).

    Columns
    -------
    id                Auto-increment surrogate PK.
    source            ``auto`` or ``manual``.  App-validated; no DB CHECK.
    definition_id     FK → item_definitions.id (CASCADE); nullable for free-text rows.
    name              Free-text label for definition-less manual rows.  NULL for
                      definition-linked rows (display name read live from definition).
    desired_quantity  Numeric(18,6) nullable — how much to buy.
    unit              Unit label for definition-less manual rows.  NULL for definition-
                      linked rows (unit read live from definition).
    note              Free-text note, nullable.
    purchased_at      Check-off state: NULL = open; set = checked/purchased.
    created_by        FK → users.id (SET NULL); the user who added/auto-created the row.
    created_at        Row-creation timestamp (UTC, set by DB on insert).
    updated_at        Last-update timestamp (UTC); refreshed on every ORM flush
                      that modifies the row via ``onupdate=func.now()``.
    """

    __tablename__ = "shopping_list_items"

    __table_args__ = (
        # Partial unique index: at most one auto row per definition, any purchased state.
        # sqlite_where mirrors the idiom used by the M2 serial partial-unique index.
        Index(
            "uq_shopping_list_one_auto_per_def",
            "definition_id",
            unique=True,
            sqlite_where=text("source='auto'"),
        ),
        # Non-unique index for the open/done split query.
        Index("ix_shopping_list_items_purchased_at", "purchased_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    definition_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "item_definitions.id",
            name="fk_shopping_list_items_definition_id",
            ondelete="CASCADE",
        ),
        nullable=True,
        default=None,
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    desired_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6),
        nullable=True,
        default=None,
    )
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True, default=None)
    purchased_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    created_by: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_shopping_list_items_created_by",
            ondelete="SET NULL",
        ),
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

    # Relationship to ItemDefinition — lazy loaded; eagerly loaded by the
    # repository when listing items so the route layer can resolve name/unit
    # without triggering N+1 queries.
    definition: Mapped[ItemDefinition | None] = relationship(
        "ItemDefinition",
        foreign_keys=[definition_id],
        lazy="select",
    )

    # Relationship to User (author) — lazy by default.
    creator: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[created_by],
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"ShoppingListItem(id={self.id!r}, source={self.source!r}, "
            f"definition_id={self.definition_id!r}, purchased_at={self.purchased_at!r})"
        )
