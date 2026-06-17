"""Pydantic request/response schemas for Location endpoints.

Schemas are thin wire DTOs; business logic lives in the service layer.
All response schemas use ``from_attributes = True`` so they can be constructed
directly from SQLAlchemy ORM objects.

Step 4 additions:
- ``LocationUpdate`` now accepts ``item_instance_id`` (the container-as-item
  bridge); ``LocationService`` validates and applies it.
- ``LocationResponse`` and ``LocationTreeNode`` expose ``item_instance_id``
  so the frontend can display and navigate the bridge.

Container-label followup:
- ``container_asset_label`` is a computed, read-only field populated by the
  service layer (not a DB column).  For a container-as-item location it holds
  the human-readable identity of the linked asset, e.g. ``"Lboxx-136"`` or
  ``"Lboxx-136 · SN 12345"``.  ``None`` for non-container locations.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class LocationCreate(BaseModel):
    """Body for POST /locations."""

    name: str
    description: str | None = None
    parent_id: int | None = None


class LocationUpdate(BaseModel):
    """Body for PATCH /locations/{id} — all fields optional."""

    name: str | None = None
    description: str | None = None
    parent_id: int | None = None
    item_instance_id: int | None = None


class LocationResponse(BaseModel):
    """Public representation of a Location (flat, no children).

    ``container_asset_label`` is a computed field injected by the service
    layer; it is NOT directly read from the ORM object via from_attributes.
    """

    id: int
    name: str
    description: str | None
    parent_id: int | None
    item_instance_id: int | None
    container_asset_label: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class LocationTreeNode(BaseModel):
    """Recursive tree node for GET /locations/tree.

    ``container_asset_label`` is a computed field injected by the service
    layer; it is NOT directly read from the ORM object via from_attributes.
    """

    id: int
    name: str
    description: str | None
    parent_id: int | None
    item_instance_id: int | None
    container_asset_label: str | None = None
    created_at: datetime
    children: list[LocationTreeNode] = []

    model_config = {"from_attributes": True}
