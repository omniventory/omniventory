"""Barcode and product-lookup endpoints (M5 Step 5).

All endpoints require a valid session.

Routes (all under the api_prefix, e.g. /api):
    GET    /definitions/{definition_id}/barcodes
        List all barcodes bound to a definition.
    POST   /definitions/{definition_id}/barcodes
        Bind a new code to a definition.
    DELETE /barcodes/{barcode_id}
        Unbind (delete) a barcode.
    GET    /barcodes/lookup?code=
        Run the product-lookup provider chain for a scanned code.
        Always returns 200; ``found=false`` signals an unknown code.

Error contract:
    401  No/invalid session.
    404  Item definition not found / barcode not found.
    409  barcode.duplicate (code already bound).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.context import RequestContext, get_authenticated_context
from app.core.errors import ErrorResponse
from app.db.session import get_db
from app.schemas.barcode import (
    BarcodeCreate,
    BarcodeLookupResponse,
    BarcodeResponse,
    DefinitionSummaryResponse,
)
from app.services.barcode import BarcodeService

_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}

router = APIRouter(tags=["barcodes"], responses=_ERROR_RESPONSES)


def _get_service(db: Annotated[Session, Depends(get_db)]) -> BarcodeService:
    """Dependency: build and return a BarcodeService."""
    return BarcodeService(db)


# ---------------------------------------------------------------------------
# Definition-scoped barcode routes
# ---------------------------------------------------------------------------


@router.get("/definitions/{definition_id}/barcodes", response_model=list[BarcodeResponse])
def list_barcodes(
    definition_id: int,
    _ctx: Annotated[RequestContext, Depends(get_authenticated_context)],
    service: Annotated[BarcodeService, Depends(_get_service)],
) -> list[BarcodeResponse]:
    """List all barcodes bound to a definition.

    Returns an empty list if the definition has no bound codes (or does not
    exist — the list is lenient, consistent with tag/note list semantics).
    Barcodes are ordered by id (bind order).
    """
    barcodes = service.list_for_definition(definition_id)
    return [BarcodeResponse.model_validate(b) for b in barcodes]


@router.post(
    "/definitions/{definition_id}/barcodes",
    response_model=BarcodeResponse,
    status_code=status.HTTP_201_CREATED,
)
def bind_barcode(
    definition_id: int,
    body: BarcodeCreate,
    _ctx: Annotated[RequestContext, Depends(get_authenticated_context)],
    service: Annotated[BarcodeService, Depends(_get_service)],
    db: Annotated[Session, Depends(get_db)],
) -> BarcodeResponse:
    """Bind a barcode code to a definition.

    Returns 404 if the definition does not exist.
    Returns 409 (barcode.duplicate) if the code is already bound to any
    definition (same or different — one code → one definition).
    """
    barcode = service.bind(
        definition_id,
        code=body.code,
        symbology=body.symbology,
        label=body.label,
    )
    db.commit()
    db.refresh(barcode)
    return BarcodeResponse.model_validate(barcode)


# ---------------------------------------------------------------------------
# Barcode-scoped routes
# Note: /barcodes/lookup MUST be registered before /barcodes/{barcode_id}
# to avoid the literal path "lookup" being interpreted as an integer id.
# ---------------------------------------------------------------------------


@router.get("/barcodes/lookup", response_model=BarcodeLookupResponse)
def lookup_barcode(
    _ctx: Annotated[RequestContext, Depends(get_authenticated_context)],
    service: Annotated[BarcodeService, Depends(_get_service)],
    code: Annotated[str, Query(description="The raw scanned/entered barcode value.")],
) -> BarcodeLookupResponse:
    """Run the product-lookup provider chain for a scanned code.

    Always returns HTTP 200.  ``found=false`` (with null ``source`` / ``definition``
    / ``draft``) signals an unknown code — the client should offer the
    "create item" flow rather than treating this as an error.

    M5 ships the ``InternalProvider`` only: a hit means the code is already
    bound to a known definition in the ``barcodes`` table.
    """
    result = service.lookup(code)
    if result is None:
        return BarcodeLookupResponse(found=False)

    defn_summary: DefinitionSummaryResponse | None = None
    if result.definition is not None:
        defn_summary = DefinitionSummaryResponse(
            id=result.definition.id,
            name=result.definition.name,
        )

    return BarcodeLookupResponse(
        found=True,
        source=result.source,
        definition=defn_summary,
        draft=result.draft,
    )


@router.delete("/barcodes/{barcode_id}", status_code=status.HTTP_204_NO_CONTENT)
def unbind_barcode(
    barcode_id: int,
    _ctx: Annotated[RequestContext, Depends(get_authenticated_context)],
    service: Annotated[BarcodeService, Depends(_get_service)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Remove a barcode binding.

    Returns 404 (barcode.not_found) if the barcode does not exist.
    """
    service.unbind(barcode_id)
    db.commit()
