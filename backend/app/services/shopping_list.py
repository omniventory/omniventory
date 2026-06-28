"""ShoppingListService — CRUD for the shopping list (M7 §4.1 / §4.2 / §9 Step 1).

Step 1 responsibilities (CRUD only; reconcile + intake added in Steps 2/3)
---------------------------------------------------------------------------
``add_manual(definition_id?, name?, desired_quantity?, unit?, note?, created_by?)``
    Add a manual item.  Cross-field guard: at least one of definition_id / name.
    If definition_id is provided it must exist (item_definition.not_found → 404).
    Validates source='manual' against SHOPPING_LIST_SOURCES.

``edit(item_id, update_body)``
    PATCH an existing item.  Only fields present in ``update.model_fields_set``
    are applied.  Raises shopping_list.not_found (404) when the item is missing.

``check_off(item_id)``
    Stamp ``purchased_at = now(UTC)``.  Step 1 — **no intake** (no body, no
    delegation to StockInstanceService; that is Step 3).
    Raises shopping_list.not_found (404) when the item is missing.

``uncheck(item_id)``
    Clear ``purchased_at``.  Safe for auto rows because the per-def auto-row
    uniqueness is state-independent (§3.1).
    Raises shopping_list.not_found (404) when the item is missing.

``remove(item_id)``
    Hard-delete an item.
    Raises shopping_list.not_found (404) when the item is missing.

``clear_purchased()``
    Delete all rows where purchased_at IS NOT NULL.  Returns the count.

DB access only through ShoppingListRepository (roadmap §2.10).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.stock import SHOPPING_LIST_SOURCES
from app.models.shopping_list_item import ShoppingListItem
from app.repositories.item_definition import ItemDefinitionRepository
from app.repositories.shopping_list import ShoppingListRepository
from app.schemas.shopping_list import ShoppingListItemUpdate


class ShoppingListService:
    """Business-logic facade for shopping-list operations.

    This is the **single mutation choke-point** for the shopping list (the
    TickTick seam reserved in M7 §12): all writes go through here, never
    directly to the repository.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = ShoppingListRepository(db)
        self._def_repo = ItemDefinitionRepository(db)

    # ---------------------------------------------------------------------- #
    # Private helpers                                                          #
    # ---------------------------------------------------------------------- #

    def _get_or_404(self, item_id: int) -> ShoppingListItem:
        """Return a ShoppingListItem by PK or raise 404 (shopping_list.not_found)."""
        item = self._repo.get(item_id)
        if item is None:
            raise AppError(
                ErrorCode.SHOPPING_LIST_NOT_FOUND,
                status_code=404,
                params={"id": item_id},
                message=f"Shopping list item {item_id} not found.",
            )
        return item

    # ---------------------------------------------------------------------- #
    # CRUD operations                                                          #
    # ---------------------------------------------------------------------- #

    def add_manual(
        self,
        *,
        definition_id: int | None,
        name: str | None,
        desired_quantity: object | None,
        unit: str | None,
        note: str | None,
        created_by: int | None,
    ) -> ShoppingListItem:
        """Add a manual shopping-list item.

        Cross-field guard (M7 §3.1): at least one of ``definition_id`` /
        ``name`` must be provided, otherwise raises ``validation.invalid_input``
        (422).

        When ``definition_id`` is provided it must exist; raises
        ``item_definition.not_found`` (404) if not.

        Parameters
        ----------
        definition_id:
            FK to an item definition (optional for free-text items).
        name:
            Free-text label (required for definition-less items; ignored / kept
            NULL for definition-linked items because the display name is always
            read live from the definition).
        desired_quantity:
            How much to buy (Decimal / None).
        unit:
            Unit label for definition-less items.
        note:
            Optional free-text note.
        created_by:
            The acting user's id (or None if the request context carries no user).
        """
        # Cross-field guard: must have definition_id OR name.
        if definition_id is None and not name:
            raise AppError(
                ErrorCode.INVALID_INPUT,
                status_code=422,
                message="A shopping list item must have either a definition_id or a name.",
            )

        # Validate definition exists when provided.
        if definition_id is not None:
            defn = self._def_repo.get(definition_id)
            if defn is None:
                raise AppError(
                    ErrorCode.ITEM_DEFINITION_NOT_FOUND,
                    status_code=404,
                    params={"id": definition_id},
                    message=f"Item definition {definition_id} not found.",
                )

        # For definition-linked rows, leave name NULL (live-resolved from def).
        stored_name = name if definition_id is None else None

        return self._repo.create(
            source=SHOPPING_LIST_SOURCES[1],  # "manual"
            definition_id=definition_id,
            name=stored_name,
            desired_quantity=desired_quantity,  # type: ignore[arg-type]
            unit=unit,
            note=note,
            created_by=created_by,
        )

    def edit(
        self,
        item_id: int,
        update: ShoppingListItemUpdate,
    ) -> ShoppingListItem:
        """PATCH an existing shopping-list item.

        Only the fields present in ``update.model_fields_set`` are applied to
        the row; absent fields leave the row unchanged.

        Raises ``shopping_list.not_found`` (404) when the item is missing.
        """
        item = self._get_or_404(item_id)

        fields: dict[str, object] = {}
        if "name" in update.model_fields_set:
            fields["name"] = update.name
        if "desired_quantity" in update.model_fields_set:
            fields["desired_quantity"] = update.desired_quantity
        if "note" in update.model_fields_set:
            fields["note"] = update.note

        if fields:
            self._repo.update(item, **fields)
        return item

    def check_off(self, item_id: int) -> ShoppingListItem:
        """Mark a shopping-list item as purchased (check-off without intake).

        Stamps ``purchased_at = now(UTC)`` on the item.  Step 1 only stamps
        the timestamp; check-off **with** intake (Step 3) extends this.

        For auto rows this does NOT delete the row — it stays as the single
        auto row for its definition (M7 §3.1 / §4.2), and will be removed
        only by ``clear_purchased``.

        Raises ``shopping_list.not_found`` (404) when the item is missing.
        """
        item = self._get_or_404(item_id)
        now_utc = datetime.now(tz=UTC)
        return self._repo.stamp_purchased(item, now_utc)

    def uncheck(self, item_id: int) -> ShoppingListItem:
        """Revert a shopping-list item to the open/unchecked state.

        Clears ``purchased_at``.  Safe for auto rows because the per-def
        auto-row uniqueness is **state-independent** (``WHERE source='auto'``
        not ``… AND purchased_at IS NULL``), so clearing ``purchased_at``
        can never create a collision with a second auto row (M7 §3.1).

        Does NOT reverse any stock intake that may have occurred during check-
        off (a separate stock action; documented in M7 §4.2).

        Raises ``shopping_list.not_found`` (404) when the item is missing.
        """
        item = self._get_or_404(item_id)
        return self._repo.clear_purchased_at(item)

    def remove(self, item_id: int) -> None:
        """Hard-delete a shopping-list item.

        Raises ``shopping_list.not_found`` (404) when the item is missing.
        """
        item = self._get_or_404(item_id)
        self._repo.delete(item)

    def clear_purchased(self) -> int:
        """Delete all purchased (checked) items.

        Deletes all rows where ``purchased_at IS NOT NULL``, which includes
        both auto and manual rows that have been checked off.  Returns the
        count of deleted rows.
        """
        return self._repo.clear_purchased()

    def list_items(self, *, include_purchased: bool = False) -> list[ShoppingListItem]:
        """Return shopping-list items (with definition joinedloaded).

        Parameters
        ----------
        include_purchased:
            When ``True``, include checked items as well as open items.
        """
        return self._repo.list(include_purchased=include_purchased)
