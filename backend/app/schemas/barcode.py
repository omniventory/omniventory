"""Pydantic request/response schemas for Barcode and product-lookup endpoints (M5 Step 5).

Schemas are thin wire DTOs; business logic lives in the service layer.
All response schemas use ``from_attributes = True`` so they can be constructed
directly from SQLAlchemy ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Barcode CRUD schemas
# ---------------------------------------------------------------------------


class BarcodeResponse(BaseModel):
    """Public representation of a Barcode."""

    id: int
    definition_id: int
    code: str
    symbology: str
    label: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BarcodeCreate(BaseModel):
    """Body for POST /definitions/{id}/barcodes."""

    code: str = Field(..., min_length=1, max_length=128, description="The raw barcode value.")
    symbology: str = Field(
        default="unknown",
        max_length=16,
        description=(
            "Barcode type, e.g. ``ean13``, ``upca``, ``qr``, ``code128``, "
            "``internal``, ``unknown``.  App-validated; no DB CHECK."
        ),
    )
    label: str | None = Field(
        default=None,
        max_length=255,
        description="Optional human-readable label (e.g. 'single' vs 'case of 24').",
    )


# ---------------------------------------------------------------------------
# Product-lookup response schemas
# ---------------------------------------------------------------------------


class DefinitionSummaryResponse(BaseModel):
    """Lightweight summary of an item definition in a lookup response.

    Returned inside ``BarcodeLookupResponse.definition`` when the scanned code
    is bound to a known definition in the ``barcodes`` table.
    """

    id: int
    name: str

    model_config = {"from_attributes": True}


class BarcodeLookupResponse(BaseModel):
    """Response for GET /barcodes/lookup?code=.

    Always returns HTTP 200 — ``found=False`` signals an unknown code (not a
    404) so the client can offer the "create item" flow without treating the
    response as an error.

    Fields
    ------
    found (bool)
        True when a provider matched the code.
    source (str | None)
        Machine-readable provider identifier (``"internal"`` for the built-in
        barcode-table provider).  None when ``found=False``.
    definition (DefinitionSummaryResponse | None)
        Lightweight definition summary when the code is already bound in the
        ``barcodes`` table.  None for an unknown code or for future providers
        that return only ``draft`` data.
    draft (dict | None)
        Reserved for future external / LLM providers (M9) that return product
        hints (name/brand/category) for the fast-create flow.  Always None in M5.
    """

    found: bool
    source: str | None = None
    definition: DefinitionSummaryResponse | None = None
    draft: dict[str, Any] | None = None
