"""Reminders API endpoint (M4 §4.7 / §4.10 / §9 Step 3).

Routes (all under the api_prefix, e.g. /api; session-authenticated):
    POST  /reminders/run   Trigger ``ReminderEngine.run_scan()`` on demand and
                           return per-source created-notification counts.

This endpoint is the primary way to demo the engine without waiting for the
daily APScheduler job (Step 5).  It is safe to call multiple times — the engine
is idempotent (a second call in the same day creates no new notifications for
the same lots).

Error contract:
    401  No/invalid session.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.context import RequestContext, get_authenticated_context
from app.core.errors import ErrorResponse
from app.db.session import get_db
from app.schemas.reminders import ReminderRunSummary
from app.services.reminder_engine import ReminderEngine

_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
}

router = APIRouter(tags=["reminders"], responses=_ERROR_RESPONSES)


def _get_engine(db: Session = Depends(get_db)) -> ReminderEngine:
    """Dependency: build and return a ReminderEngine bound to the current DB session."""
    return ReminderEngine(db)


@router.post("/reminders/run", response_model=ReminderRunSummary)
def run_reminders(
    _ctx: Annotated[RequestContext, Depends(get_authenticated_context)],
    engine: Annotated[ReminderEngine, Depends(_get_engine)],
) -> ReminderRunSummary:
    """Trigger the reminder engine scan on demand.

    Evaluates all date sources (best_before, warranty) across all active users
    and creates idempotent in-app notification rows.  Returns the count of
    *newly created* rows per source; zero means "nothing new this scan" (either
    no lots qualify or they were already notified).

    Re-running is safe: the engine uses a unique ``(user_id, dedup_key)`` to
    prevent duplicate notifications.

    The ``get_db`` dependency auto-commits the session after this handler
    returns, so newly created notification rows are durably persisted.
    External channel dispatch (Phase C) runs after commit; in Step 3 no external
    I/O occurs (dispatcher is a no-op).
    """
    summary = engine.run_scan()
    return ReminderRunSummary(
        best_before=summary.best_before,
        warranty=summary.warranty,
        low_stock=summary.low_stock,
    )
