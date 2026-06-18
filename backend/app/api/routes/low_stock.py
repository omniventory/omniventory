"""Low-stock computed endpoint (M2 §4.5 / §4.6).

Routes (all under the api_prefix, e.g. /api; all authenticated):
    GET  /low-stock    Return the computed list of low-stock definitions.

This endpoint is a pure read — it never writes to the DB.  Business logic
(the per-mode low-stock rule) lives entirely in ``LowStockService``; this
route only authenticates the caller and delegates.

Error contract:
    401  No/invalid session.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.context import RequestContext, get_authenticated_context
from app.core.errors import ErrorResponse
from app.db.session import get_db
from app.schemas.low_stock import LowStockItem
from app.services.low_stock import LowStockService

_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
}

router = APIRouter(tags=["low-stock"], responses=_ERROR_RESPONSES)


def _get_service(db: Session = Depends(get_db)) -> LowStockService:
    """Dependency: build and return a LowStockService."""
    return LowStockService(db)


@router.get("/low-stock", response_model=list[LowStockItem])
def get_low_stock(
    _ctx: Annotated[RequestContext, Depends(get_authenticated_context)],
    service: Annotated[LowStockService, Depends(_get_service)],
) -> list[LowStockItem]:
    """Return the computed list of definitions that are currently low on stock.

    Applies the per-mode low-stock rule across all definitions:
    - ``exact`` mode with ``min_stock`` set: flagged when SUM(lot quantities)
      is strictly below ``min_stock``.
    - ``level`` mode: flagged when any lot is at ``stock_level='low'``.
    - ``none`` mode: never flagged.

    Returns an empty list when nothing is low.  This is a pure computed read
    — no state is persisted.
    """
    return service.compute()
