"""Pydantic response schema for StockMovement.

``MovementResponse`` is the public wire representation of a single ledger row.
It is the full shape described in M2 §4.8 and will be returned by the
movement-history endpoint (``GET /instances/{id}/movements``) and the
individual operation endpoints once they are wired in Step 4.

Notes
-----
- ``quantity_delta`` is ``Decimal`` (never float) per roadmap §2.9.
  Pydantic serialises Python ``Decimal`` as a JSON string by default when
  ``model_config = {"from_attributes": True}`` and the field type is
  ``Decimal``; this keeps the wire format consistent with other Decimal fields
  in the codebase (e.g. ``InstanceResponse.quantity``).
- All nullable FK fields (``from_location_id``, ``to_location_id``,
  ``reverses_movement_id``, ``user_id``) are typed as ``int | None``.
- ``from_attributes = True`` allows constructing this schema directly from a
  SQLAlchemy ``StockMovement`` ORM object.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class MovementResponse(BaseModel):
    """Public representation of a stock_movements ledger row (M2 §4.8)."""

    id: int
    instance_id: int
    type: str
    quantity_delta: Decimal
    from_location_id: int | None
    to_location_id: int | None
    occurred_at: datetime
    note: str | None
    reverses_movement_id: int | None
    user_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
