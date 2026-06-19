"""Pydantic schema for the expiring/expired computed signal (M3 §4.6).

``ExpiringItem`` is the public wire shape returned by ``GET /expiring``.
One item per *lot* (stock instance) whose ``best_before_date`` is not NULL
and falls within (or before) the requested horizon — so the response set is
``expired ∪ expiring-within-N``.

Fields
------
instance_id
    PK of the StockInstance (lot).
definition_id
    PK of the parent ItemDefinition.
name
    Human-readable name of the definition (avoids a second round-trip in
    the UI — same pattern as LowStockItem).
location_id
    FK of the lot's current location; ``None`` when unassigned.
best_before_date
    The lot's best-before date (always non-NULL for items in this list).
quantity
    For ``exact``-mode lots: the current quantity (Decimal, as string on the
    wire — roadmap §2.9).  ``None`` for ``level``/``none``-mode lots.
days_remaining
    ``(best_before_date - today).days``.  Negative = already expired.
status
    ``'expired'`` when ``days_remaining < 0``; ``'expiring'`` otherwise.

Notes
-----
- Granularity is **per-lot** (unlike ``LowStockItem``'s per-definition
  granularity) because expiry is a batch property (roadmap §2.4).
- ``Decimal`` for quantity (roadmap §2.9); ``date`` for the date.
- ``status`` and ``days_remaining`` are computed by ``ExpiryService`` — the
  DB stores only ``best_before_date``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class ExpiringItem(BaseModel):
    """Public representation of a single expiring/expired lot (M3 §4.6)."""

    instance_id: int
    definition_id: int
    name: str
    location_id: int | None
    best_before_date: date
    quantity: Decimal | None
    days_remaining: int
    status: str  # 'expired' | 'expiring'

    model_config = {"from_attributes": True}
