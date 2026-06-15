"""Request context abstraction — the multi-tenant hedge.

``RequestContext`` is a lightweight dataclass that holds the request-scoped
resolved objects a route handler or service needs.  As of Step 4 it carries
both the current ``Household`` and the optional current ``User``.

``get_context`` is a FastAPI dependency that resolves the singleton household
and returns a ``RequestContext`` ready to inject.

``get_authenticated_context`` additionally resolves the current user via the
session cookie (use this on authenticated routes that also need the context).

Why a single "context" object?
-------------------------------
All DB access goes through a centralized context + repository layer (roadmap
§1.2 / §2.10).  This is the "cheap insurance" that makes a future switch to
multi-tenancy a contained change:
- Today: ``context.household`` is always the singleton row (id=1).
- Tomorrow (multi-tenant): resolve the household from a JWT/subdomain claim,
  add a ``household_id`` scope filter in one place, done.

No raw queries appear in route handlers — they depend on ``get_context`` /
``get_authenticated_context`` and call repository methods via the context.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.household import Household
from app.models.user import User
from app.repositories.household import HouseholdRepository


@dataclass(frozen=True)
class RequestContext:
    """Immutable request-scoped context.

    Attributes
    ----------
    household
        The current (singleton) Household resolved for this request.
    user
        The authenticated ``User`` for this request, or ``None`` for
        unauthenticated endpoints (e.g. ``/health``, ``/auth/login``).
    """

    household: Household
    user: User | None = field(default=None)


def get_context(db: Session = Depends(get_db)) -> RequestContext:
    """FastAPI dependency: resolve and return the current request context.

    Resolves the singleton Household (unauthenticated variant — no user).
    Use this for public endpoints such as ``/health``.
    """
    repo = HouseholdRepository(db)
    household = repo.ensure()
    return RequestContext(household=household)


def get_authenticated_context(
    request: Request,
    db: Session = Depends(get_db),
) -> RequestContext:
    """FastAPI dependency: resolve context including the authenticated user.

    Combines household resolution with session-cookie auth.  Use this on
    routes that need both the context and the current user.

    Raises ``HTTP 401`` (via ``get_current_user``) if the session is missing
    or expired.
    """
    from app.api.deps import get_current_user

    repo = HouseholdRepository(db)
    household = repo.ensure()
    user = get_current_user(request=request, db=db)
    return RequestContext(household=household, user=user)
