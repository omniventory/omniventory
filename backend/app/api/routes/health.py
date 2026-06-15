"""Health check endpoint.

GET /health (mounted under the configured api_prefix, e.g. /api/health)

Step 2 response: ``{status, version, api_version}``
Step 3 response: ``{status, version, api_version, db}``

The ``db`` field performs a trivial ``SELECT 1`` via ``HouseholdRepository``
so that health reflects DB reachability.  Raw SQL is NOT inlined here —
``HouseholdRepository.db_ping()`` owns that probe, keeping the route handler
free of direct queries.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.repositories.household import HouseholdRepository

router = APIRouter()


class HealthResponse(BaseModel):
    """Shape of the /health response (Step 3+)."""

    status: str
    version: str
    api_version: int
    db: str


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    """Return service health.

    ``status``      always ``"ok"`` while the process is running.
    ``version``     application release version.
    ``api_version`` integer compatibility number from Settings.
    ``db``          ``"ok"`` if ``SELECT 1`` succeeds; propagates exception
                    on DB failure (FastAPI returns 500).
    """
    from importlib.metadata import PackageNotFoundError, version

    settings = get_settings()

    try:
        app_version = version("omniventory")
    except PackageNotFoundError:
        app_version = "dev"

    # DB probe — no raw SQL in the route; the repository owns the query.
    repo = HouseholdRepository(db)
    repo.db_ping()

    return HealthResponse(
        status="ok",
        version=app_version,
        api_version=settings.api_version,
        db="ok",
    )
