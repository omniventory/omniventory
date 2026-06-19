"""Expiring/expired computed endpoint (M3 §4.4 / §4.5).

Routes (all under the api_prefix, e.g. /api; all authenticated):
    GET  /expiring    Return the computed list of expiring/expired lots.

Query parameters:
    within_days   integer, default 30, clamped >= 0 in the service.
                  ``0`` => only expired + expiring-today.
                  Negative values are clamped to 0 (never rejected).

This endpoint is a pure read — it never writes to the DB.  Business logic
(the live-stock filter, clamp, status/days_remaining derivation) lives
entirely in ``ExpiryService``; this route only authenticates the caller and
delegates.

Error contract:
    401  No/invalid session.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.context import RequestContext, get_authenticated_context
from app.core.errors import ErrorResponse
from app.db.session import get_db
from app.schemas.expiry import ExpiringItem
from app.services.expiry import ExpiryService

_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
}

router = APIRouter(tags=["expiry"], responses=_ERROR_RESPONSES)


def _get_service(db: Session = Depends(get_db)) -> ExpiryService:
    """Dependency: build and return an ExpiryService."""
    return ExpiryService(db)


@router.get("/expiring", response_model=list[ExpiringItem])
def get_expiring(
    _ctx: Annotated[RequestContext, Depends(get_authenticated_context)],
    service: Annotated[ExpiryService, Depends(_get_service)],
    within_days: Annotated[
        int,
        Query(
            description=(
                "Return lots expiring within this many days from today (inclusive). "
                "``0`` means only expired and expiring-today. "
                "Negative values are clamped to 0."
            )
        ),
    ] = 30,
) -> list[ExpiringItem]:
    """Return the computed list of lots that are expiring or already expired.

    The response set is ``expired ∪ expiring-within-N``:
    - A lot is included when ``best_before_date <= today + within_days``
      and the lot is not a depleted ``exact`` lot (``quantity IS NULL OR
      quantity > 0``).
    - Each item carries ``status`` (``'expired'`` or ``'expiring'``) and
      ``days_remaining`` (negative = past; 0 = today; positive = future).
    - Ordered soonest-first (expired lots naturally lead).

    ``within_days`` defaults to 30 and is clamped to ``>= 0`` by the service
    — negative values are never rejected (they behave as 0).

    Returns an empty list when nothing qualifies.  This is a pure computed
    read — no state is persisted.
    """
    return service.compute(within_days)
