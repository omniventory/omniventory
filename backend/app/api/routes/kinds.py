"""Item kinds read-only endpoint.

All endpoints require a valid session (via ``get_authenticated_context``).
``item_kinds`` is read-only in M1 — no write endpoints are exposed here.
Kinds CRUD and per-kind behaviour flags are deferred to M1.md §12.

Routes (all under the api_prefix, e.g. /api):
    GET  /kinds    Return the flat list of all item kinds.

Error contract:
    401  No/invalid session.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.context import RequestContext, get_authenticated_context
from app.core.errors import ErrorResponse
from app.db.session import get_db
from app.repositories.item_kind import ItemKindRepository
from app.schemas.item_kind import KindResponse

_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

router = APIRouter(prefix="/kinds", tags=["kinds"], responses=_ERROR_RESPONSES)


def _get_repo(db: Session = Depends(get_db)) -> ItemKindRepository:
    """Dependency: build and return an ItemKindRepository."""
    return ItemKindRepository(db)


@router.get("", response_model=list[KindResponse])
def list_kinds(
    _ctx: Annotated[RequestContext, Depends(get_authenticated_context)],
    repo: Annotated[ItemKindRepository, Depends(_get_repo)],
) -> list[KindResponse]:
    """Return all item kinds (seeded: durable / consumable / perishable).

    This endpoint is read-only — there are no write endpoints for kinds in M1.
    """
    kinds = repo.list_all()
    return [KindResponse.model_validate(k) for k in kinds]
