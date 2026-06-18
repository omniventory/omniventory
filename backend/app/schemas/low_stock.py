"""Pydantic schema for the low-stock signal (M2 §4.5 / §4.8).

``LowStockItem`` is the public wire shape returned by ``GET /low-stock``.
One item per *definition* that is currently low, not per lot.

Fields
------
definition_id
    PK of the flagged ItemDefinition.
name
    Human-readable name of the definition (the UI doesn't need a second
    round-trip to show it).
mode
    The definition's stock_tracking_mode: ``'exact'`` or ``'level'``.
    (``'none'`` definitions are never flagged.)
reason
    Why it is flagged:
    - ``'below_min_stock'``: ``exact`` mode, SUM(lot quantities) < min_stock.
    - ``'level_low'``      : ``level`` mode, at least one lot is at ``'low'``.
current
    For ``exact`` mode: the current total quantity (Decimal, as string on the
    wire — roadmap §2.9).  ``None`` for ``level`` mode.
threshold
    For ``exact`` mode: the definition's min_stock threshold (Decimal, as
    string on the wire).  ``None`` for ``level`` mode.

Notes
-----
- ``current`` and ``threshold`` are both ``None`` for ``level``-mode items
  (there is no numeric total — the signal is qualitative).
- ``Decimal`` fields are serialised as JSON strings by Pydantic's default
  JSON encoder when ``model_config = {"from_attributes": True}`` is set,
  matching the existing ``InstanceResponse.quantity`` / ``DefinitionResponse.min_stock``
  wire convention.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class LowStockItem(BaseModel):
    """Public representation of a single low-stock definition (M2 §4.5 / §4.8)."""

    definition_id: int
    name: str
    mode: str
    reason: str
    current: Decimal | None
    threshold: Decimal | None

    model_config = {"from_attributes": True}
