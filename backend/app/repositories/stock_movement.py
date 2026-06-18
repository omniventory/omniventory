"""Repository for the StockMovement (stock_movements) table.

Pure data access — no business rules here.  All business logic (mode guards,
non-negative checks, FIFO ordering, reversal rules) lives in the service layer
(``app.services.stock_movement``, added in M2 Step 4).

The ledger is **append-only**: there is deliberately **no** ``update`` method.
A mistake is corrected by appending a compensating movement, never by mutating
existing rows (M2 §2 — "append-only ledger").

Public methods
--------------
append(...)                       Insert one movement row and flush.
get(id)                           Return a StockMovement by PK, or None.
list_for_instance(instance_id)    History for a lot, newest-first.
sum_delta_for_instance(instance_id)
                                  COALESCE(SUM(quantity_delta), 0) as Decimal.
find_reversal_of(movement_id)     The row that reverses movement_id, or None.
delete_for_instance(instance_id)  Bulk-delete all movements for a lot.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.stock_movement import StockMovement


class StockMovementRepository:
    """Data-access object for the stock_movements table."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ---------------------------------------------------------------------- #
    # Write                                                                    #
    # ---------------------------------------------------------------------- #

    def append(
        self,
        *,
        instance_id: int,
        type: str,
        quantity_delta: Decimal,
        from_location_id: int | None = None,
        to_location_id: int | None = None,
        occurred_at: datetime | None = None,
        note: str | None = None,
        reverses_movement_id: int | None = None,
        user_id: int | None = None,
    ) -> StockMovement:
        """Insert one movement row and flush to obtain its PK.

        Parameters
        ----------
        instance_id
            The lot (stock_instances.id) this movement belongs to.
        type
            Movement type string — validated app-layer against MOVEMENT_TYPES
            before this call (not checked here).
        quantity_delta
            Signed quantity change.  Positive for intake, negative for
            consume/discard, 0 for move, ± for adjust/correction.
        from_location_id
            Source location; set on ``move`` movements (and intake for provenance).
        to_location_id
            Destination location; set on ``move`` movements (and intake).
        occurred_at
            Physical-event time (back-dateable).  Defaults to DB ``now()``
            when None (the ``server_default`` handles it).
        note
            Optional free-text annotation.
        reverses_movement_id
            PK of the movement this entry reverses, if any.
        user_id
            Acting user (FK → users.id); None for system / backfill movements.
        """
        kwargs: dict[str, object] = {
            "instance_id": instance_id,
            "type": type,
            "quantity_delta": quantity_delta,
            "from_location_id": from_location_id,
            "to_location_id": to_location_id,
            "note": note,
            "reverses_movement_id": reverses_movement_id,
            "user_id": user_id,
        }
        if occurred_at is not None:
            kwargs["occurred_at"] = occurred_at

        movement = StockMovement(**kwargs)
        self._db.add(movement)
        self._db.flush()
        return movement

    # ---------------------------------------------------------------------- #
    # Read                                                                     #
    # ---------------------------------------------------------------------- #

    def get(self, movement_id: int) -> StockMovement | None:
        """Return a StockMovement by PK, or None if not found."""
        return self._db.get(StockMovement, movement_id)

    def list_for_instance(self, instance_id: int) -> list[StockMovement]:
        """Return all movements for a lot, ordered newest-first.

        Order: ``(occurred_at DESC, id DESC)`` — the most recent event first,
        with ``id`` as the tie-breaker for events with identical timestamps
        (M2 §4.6 ``GET .../movements`` spec).
        """
        stmt = (
            select(StockMovement)
            .where(StockMovement.instance_id == instance_id)
            .order_by(StockMovement.occurred_at.desc(), StockMovement.id.desc())
        )
        return list(self._db.scalars(stmt).all())

    def sum_delta_for_instance(self, instance_id: int) -> Decimal:
        """Return COALESCE(SUM(quantity_delta), 0) for a lot as a Decimal.

        This is the ledger-derived quantity — the single source of truth
        for an ``exact``-mode lot's current stock (M2 §4.2).

        Returns ``Decimal("0")`` when the lot has no movements at all
        (e.g. immediately after creation, before any intake is recorded).
        """
        stmt = select(func.coalesce(func.sum(StockMovement.quantity_delta), 0)).where(
            StockMovement.instance_id == instance_id
        )
        result = self._db.scalar(stmt)
        # SQLAlchemy may return an int (0) or a DB-native Decimal depending on
        # the driver; normalise to Python Decimal for type-safety (roadmap §2.9).
        return Decimal(str(result)) if result is not None else Decimal("0")

    def find_reversal_of(self, movement_id: int) -> StockMovement | None:
        """Return the movement that reverses ``movement_id``, or None.

        Used by the service layer to enforce the "a movement can be reversed
        at most once" rule before the DB partial-unique index would fire.
        """
        stmt = select(StockMovement).where(StockMovement.reverses_movement_id == movement_id)
        return self._db.scalars(stmt).first()

    # ---------------------------------------------------------------------- #
    # Bulk delete (used when a lot is being deleted via service layer)         #
    # ---------------------------------------------------------------------- #

    def delete_for_instance(self, instance_id: int) -> None:
        """Delete all movements belonging to ``instance_id``.

        In practice the ``ondelete="CASCADE"`` FK on ``instance_id`` handles
        this automatically when the parent ``StockInstance`` row is deleted.
        This method is provided for cases where the caller needs explicit
        control (e.g. the Step 3 downgrade deletes backfilled movements before
        reverting the nullable-quantity column).
        """
        stmt = select(StockMovement).where(StockMovement.instance_id == instance_id)
        for movement in self._db.scalars(stmt).all():
            self._db.delete(movement)
        self._db.flush()
