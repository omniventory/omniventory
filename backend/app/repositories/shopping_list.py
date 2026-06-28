"""Repository for the ShoppingListItem table (M7 §4.1 / §9 Step 1).

All DB access to the ``shopping_list_items`` table goes through this class.
Route handlers and services must not issue raw queries; they call
``ShoppingListRepository`` methods.

Public methods (Step 1 — CRUD only; reconcile helpers added in Step 2)
-----------------------------------------------------------------------
``create(...)``
    Insert and flush a new ShoppingListItem row.

``get(item_id)``
    Return a ShoppingListItem by PK (with definition joinedloaded), or None.

``list(include_purchased, ...)``
    Return all items (open first, then purchased) with definition joinedloaded.

``update(item, **fields)``
    Apply field updates to an existing row and flush.

``delete(item)``
    Delete a ShoppingListItem row and flush.

``clear_purchased()``
    Delete all rows where ``purchased_at IS NOT NULL``; return the count of
    deleted rows.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import case, delete, select
from sqlalchemy.orm import Session, joinedload

from app.models.shopping_list_item import ShoppingListItem


class ShoppingListRepository:
    """Data-access object for the shopping_list_items table."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ---------------------------------------------------------------------- #
    # Read                                                                     #
    # ---------------------------------------------------------------------- #

    def get(self, item_id: int) -> ShoppingListItem | None:
        """Return a ShoppingListItem by PK with its definition joinedloaded, or None."""
        stmt = (
            select(ShoppingListItem)
            .options(joinedload(ShoppingListItem.definition))
            .where(ShoppingListItem.id == item_id)
        )
        return self._db.execute(stmt).scalar_one_or_none()

    def list(self, *, include_purchased: bool = False) -> list[ShoppingListItem]:
        """Return shopping list items with definition joinedloaded.

        Ordering: open items (``purchased_at IS NULL``) first, then purchased,
        each sub-group sorted by ``created_at ASC`` for stable ordering.

        Parameters
        ----------
        include_purchased:
            When ``True``, include checked/purchased items in the result.
            When ``False`` (default), return only open items.
        """
        stmt = (
            select(ShoppingListItem)
            .options(joinedload(ShoppingListItem.definition))
            # Open items (0) before purchased items (1); stable secondary order.
            .order_by(
                case((ShoppingListItem.purchased_at.is_(None), 0), else_=1),
                ShoppingListItem.created_at.asc(),
            )
        )
        if not include_purchased:
            stmt = stmt.where(ShoppingListItem.purchased_at.is_(None))
        return list(self._db.execute(stmt).scalars().all())

    # ---------------------------------------------------------------------- #
    # Write                                                                    #
    # ---------------------------------------------------------------------- #

    def create(
        self,
        *,
        source: str,
        definition_id: int | None = None,
        name: str | None = None,
        desired_quantity: Decimal | None = None,
        unit: str | None = None,
        note: str | None = None,
        created_by: int | None = None,
    ) -> ShoppingListItem:
        """Insert a new ShoppingListItem row and flush to get its PK.

        The caller is responsible for source validation (app-layer) and the
        cross-field name/definition_id check before calling this method.
        """
        item = ShoppingListItem(
            source=source,
            definition_id=definition_id,
            name=name,
            desired_quantity=desired_quantity,
            unit=unit,
            note=note,
            created_by=created_by,
        )
        self._db.add(item)
        self._db.flush()
        return item

    def update(self, item: ShoppingListItem, **fields: object) -> ShoppingListItem:
        """Apply field updates to an existing ShoppingListItem and flush.

        Only the keys present in ``fields`` are updated.  Pass keyword
        arguments for each column you want to change.

        SQLAlchemy's ``onupdate=func.now()`` on ``updated_at`` ensures the
        timestamp is refreshed when the row is flushed.
        """
        for key, value in fields.items():
            setattr(item, key, value)
        self._db.flush()
        return item

    def delete(self, item: ShoppingListItem) -> None:
        """Delete a ShoppingListItem row and flush."""
        self._db.delete(item)
        self._db.flush()

    def clear_purchased(self) -> int:
        """Delete all rows where ``purchased_at IS NOT NULL``.

        Returns the number of deleted rows.

        Uses a bulk DELETE for efficiency.  After the DELETE the session is
        flushed so the caller's subsequent queries reflect the change.
        """
        # Count first (needed because bulk DELETE doesn't expose rowcount
        # reliably across all SQLAlchemy dialects; explicit count is safe).
        count_stmt = select(ShoppingListItem).where(ShoppingListItem.purchased_at.is_not(None))
        rows = list(self._db.execute(count_stmt).scalars().all())
        count = len(rows)
        if count == 0:
            return 0

        bulk_stmt = (
            delete(ShoppingListItem)
            .where(ShoppingListItem.purchased_at.is_not(None))
            .execution_options(synchronize_session="fetch")
        )
        self._db.execute(bulk_stmt)
        self._db.flush()
        return count

    # ---------------------------------------------------------------------- #
    # Helpers used by check-off / uncheck (Step 1)                            #
    # ---------------------------------------------------------------------- #

    def stamp_purchased(self, item: ShoppingListItem, at: datetime) -> ShoppingListItem:
        """Set ``purchased_at`` on an item (check-off).

        Does not validate existence — the caller must fetch the item first.
        """
        item.purchased_at = at
        self._db.flush()
        return item

    def clear_purchased_at(self, item: ShoppingListItem) -> ShoppingListItem:
        """Clear ``purchased_at`` on an item (uncheck).

        Does not validate existence — the caller must fetch the item first.
        """
        item.purchased_at = None
        self._db.flush()
        return item
