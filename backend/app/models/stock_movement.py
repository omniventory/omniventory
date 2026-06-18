"""SQLAlchemy model for the StockMovement (stock_movements) table.

``stock_movements`` is the append-only typed transaction log for the stock
ledger introduced in M2.  Every change to an ``exact``-mode lot's quantity
is represented as a movement row; the lot's current quantity is derived from
``SUM(quantity_delta)`` over its movements (roadmap §2.3 — the "never blind-
overwrite" red line).

Design notes
------------
- ``instance_id`` → ``stock_instances.id`` with ``ondelete="CASCADE"``: when a
  lot is deleted its entire ledger history goes with it (M2 §2 non-goals —
  soft-delete is deferred).
- ``quantity_delta`` is ``Numeric(18,6)`` — **never float** (roadmap §2.9).
  Signed: positive for intake, negative for consume/discard, 0 for move,
  ± for adjust/correction.
- ``reverses_movement_id`` is a self-FK with ``ondelete="SET NULL"`` (if the
  original movement is somehow deleted, the reversal link becomes NULL rather
  than cascading the deletion).  A **partial unique index** on this column
  WHERE NOT NULL enforces the "a movement can be reversed at most once" rule
  at the DB level (M2 §2 / §3.3).
- ``type`` is validated **app-layer** against ``MOVEMENT_TYPES`` — no DB CHECK
  (roadmap §2.11).
- ``occurred_at`` is the physical-receipt / physical-event time (back-dateable);
  ``created_at`` is the row-creation timestamp set by the DB.
- ``from_location_id`` / ``to_location_id`` — recorded on ``move`` (and on
  ``intake`` for provenance); ``ondelete="SET NULL"`` so deleting a location
  does not cascade-delete movement history.
- ``user_id`` is the acting user (audit spine for M6); nullable so the
  backfill / system-generated movements can carry NULL.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StockMovement(Base):
    """An append-only ledger entry for a stock lot.

    Columns
    -------
    id                    Auto-increment surrogate PK.
    instance_id           FK → stock_instances.id; NOT NULL; CASCADE on delete.
    type                  Movement type string; validated app-layer.
    quantity_delta        Signed Numeric(18,6); source of truth for quantity.
    from_location_id      FK → locations.id; SET NULL on delete; for move/intake.
    to_location_id        FK → locations.id; SET NULL on delete; for move/intake.
    occurred_at           When the event happened (back-dateable); default now().
    note                  Optional free-text (up to 1 000 chars).
    reverses_movement_id  Self-FK; SET NULL on delete; partial-unique when NOT NULL.
    user_id               FK → users.id; SET NULL on delete; acting user.
    created_at            Row-creation timestamp (UTC, set by DB on insert).
    """

    __tablename__ = "stock_movements"

    __table_args__ = (
        # Fast look-up of all movements for a lot.
        Index("ix_stock_movements_instance_id", "instance_id"),
        # Composite index for history ordering: newest-first by (instance, time).
        Index("ix_stock_movements_instance_occurred", "instance_id", "occurred_at"),
        # Partial unique index: a movement can only be reversed once.
        # NULL reverses_movement_id values (= not a reversal) are excluded so
        # any number of non-reversal rows can coexist.
        Index(
            "uq_stock_movements_reversal",
            "reverses_movement_id",
            unique=True,
            sqlite_where=text("reverses_movement_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    instance_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "stock_instances.id",
            name="fk_stock_movements_instance_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    type: Mapped[str] = mapped_column(String(20), nullable=False)

    # Signed quantity change.  Positive = stock in; negative = stock out; 0 = move.
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)

    from_location_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "locations.id",
            name="fk_stock_movements_from_location_id",
            ondelete="SET NULL",
        ),
        nullable=True,
        default=None,
    )

    to_location_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "locations.id",
            name="fk_stock_movements_to_location_id",
            ondelete="SET NULL",
        ),
        nullable=True,
        default=None,
    )

    # Physical event time — back-dateable; distinct from created_at.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    note: Mapped[str | None] = mapped_column(String(1000), nullable=True, default=None)

    # Self-referencing FK: points to the movement this entry reverses, if any.
    # ondelete="SET NULL" — losing the original does not delete the reversal.
    reverses_movement_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "stock_movements.id",
            name="fk_stock_movements_reverses_movement_id",
            ondelete="SET NULL",
        ),
        nullable=True,
        default=None,
    )

    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_stock_movements_user_id",
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

    def __repr__(self) -> str:
        return (
            f"StockMovement(id={self.id!r}, instance_id={self.instance_id!r}, "
            f"type={self.type!r}, quantity_delta={self.quantity_delta!r})"
        )
