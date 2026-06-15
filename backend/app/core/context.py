"""Request context abstraction — the multi-tenant hedge.

``RequestContext`` is a lightweight dataclass that holds the request-scoped
resolved objects a route handler or service needs.  In Step 3 it carries only
the current ``Household``; Step 4 will add the current ``User`` here once the
auth layer exists.

``get_context`` is a FastAPI dependency that resolves the singleton household
and returns a ``RequestContext`` ready to inject.

Why a single "context" object?
-------------------------------
All DB access goes through a centralized context + repository layer (roadmap
§1.2 / §2.10).  This is the "cheap insurance" that makes a future switch to
multi-tenancy a contained change:
- Today: ``context.household`` is always the singleton row (id=1).
- Tomorrow (multi-tenant): resolve the household from a JWT/subdomain claim,
  add a ``household_id`` scope filter in one place, done.

No raw queries appear in route handlers — they depend on ``get_context`` and
call repository methods on ``context.household`` or the injected session.
"""

from dataclasses import dataclass

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.household import Household
from app.repositories.household import HouseholdRepository


@dataclass(frozen=True)
class RequestContext:
    """Immutable request-scoped context.

    Attributes
    ----------
    household
        The current (singleton) Household resolved for this request.

    Note: ``user`` will be added in Step 4.
    """

    household: Household


def get_context(db: Session = Depends(get_db)) -> RequestContext:
    """FastAPI dependency: resolve and return the current request context.

    Ensures the singleton Household exists (creates it on first boot if
    absent) and wraps it in a ``RequestContext`` for injection into routes
    and services.
    """
    repo = HouseholdRepository(db)
    household = repo.ensure()
    return RequestContext(household=household)
