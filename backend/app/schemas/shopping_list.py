"""Pydantic request/response schemas for shopping-list endpoints (M7 Step 1).

Schemas are thin wire DTOs; business logic lives in the service layer.

ShoppingListItemResponse
    Public representation of a shopping-list row.  ``name`` and ``unit`` are
    **resolved live**: for definition-linked rows the definition's current name
    and unit are used; for free-text rows the row's own name/unit are used.
    The route layer performs this resolution via ``ShoppingListItemResponse.from_item``
    (the definition relationship must be loaded before calling).

ShoppingListItemCreate
    Body for ``POST /shopping-list``.  At least one of ``definition_id`` / ``name``
    must be provided (enforced by the service layer, not Pydantic, so the error
    code is ``validation.invalid_input`` with a useful message).

ShoppingListItemUpdate
    Body for ``PATCH /shopping-list/{id}``.  PATCH semantics via
    ``model_fields_set``: only fields explicitly included in the request body
    are applied; absent fields are left unchanged.

ClearPurchasedResponse
    Response for ``POST /shopping-list/clear-purchased``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.models.shopping_list_item import ShoppingListItem


class ShoppingListItemResponse(BaseModel):
    """Public representation of one shopping-list row.

    ``name`` and ``unit`` are resolved from the linked definition when
    ``definition_id`` is set; otherwise they carry the row's own free-text
    values.  Use ``ShoppingListItemResponse.from_item(item)`` to build this
    from an ORM object with its definition relationship already loaded.
    """

    id: int
    source: str
    definition_id: int | None
    name: str | None
    desired_quantity: Decimal | None
    unit: str | None
    note: str | None
    purchased_at: datetime | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_item(cls, item: ShoppingListItem) -> ShoppingListItemResponse:
        """Build a response from a ShoppingListItem ORM object.

        The ``definition`` relationship must be loaded (either eagerly via
        joinedload or already accessed) before calling this.

        Resolution rules (M7 §3.1 / §4.8):
        - ``name``: definition.name if definition is loaded, else item.name.
        - ``unit``: definition.unit if definition is loaded, else item.unit.
        """
        resolved_name: str | None = item.name
        resolved_unit: str | None = item.unit
        if item.definition is not None:
            resolved_name = item.definition.name
            resolved_unit = item.definition.unit
        return cls(
            id=item.id,
            source=item.source,
            definition_id=item.definition_id,
            name=resolved_name,
            desired_quantity=item.desired_quantity,
            unit=resolved_unit,
            note=item.note,
            purchased_at=item.purchased_at,
            created_by=item.created_by,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )


class ShoppingListItemCreate(BaseModel):
    """Body for POST /shopping-list (add a manual item).

    At least one of ``definition_id`` / ``name`` must be provided.  This is
    enforced by the service layer (not Pydantic) so the client receives the
    stable ``validation.invalid_input`` error code.
    """

    definition_id: int | None = None
    name: str | None = Field(default=None, max_length=255)
    desired_quantity: Decimal | None = None
    unit: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=1000)


class ShoppingListItemUpdate(BaseModel):
    """Body for PATCH /shopping-list/{id}.

    PATCH semantics: only fields present in the request body are applied
    (checked via ``model_fields_set`` in the service layer).  Fields absent
    from the body leave the row unchanged.
    """

    name: str | None = Field(default=None, max_length=255)
    desired_quantity: Decimal | None = None
    note: str | None = Field(default=None, max_length=1000)


class ClearPurchasedResponse(BaseModel):
    """Response for POST /shopping-list/clear-purchased."""

    deleted_count: int
