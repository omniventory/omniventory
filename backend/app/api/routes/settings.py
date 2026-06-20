"""Settings configuration endpoint (M4 §4.10 / §9 Step 1).

Routes (all under the api_prefix, e.g. /api; all session-authenticated):
    GET   /settings   Return the full reminders + channels configuration.
                      Secrets are masked as ``*_is_set`` boolean flags.
    PATCH /settings   Apply a partial update (only supplied fields change).
                      Write-only secrets are accepted here and stored.

Error contract:
    401  No/invalid session.
    422  Pydantic validation failure → ``validation.invalid_input`` (existing
         handler in ``create_app``; no new error code needed for this step).
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.context import RequestContext, get_authenticated_context
from app.core.errors import ErrorResponse
from app.db.session import get_db
from app.schemas.settings import SettingsResponse, SettingsUpdate
from app.services.settings import SettingsService

_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
}

router = APIRouter(tags=["settings"], responses=_ERROR_RESPONSES)


def _get_service(db: Session = Depends(get_db)) -> SettingsService:
    """Dependency: build and return a SettingsService."""
    return SettingsService(db)


@router.get("/settings", response_model=SettingsResponse)
def get_settings(
    _ctx: Annotated[RequestContext, Depends(get_authenticated_context)],
    service: Annotated[SettingsService, Depends(_get_service)],
    db: Session = Depends(get_db),
) -> SettingsResponse:
    """Return the current reminders and channels configuration.

    Secrets (SMTP password, MQTT password, integration token, auth header)
    are never echoed; each is replaced by a ``*_is_set`` boolean flag.
    Un-set keys return their code-defined defaults (the table only stores
    user overrides).

    **Integration token auto-generation (Step 8):** when the HTTP channel is
    enabled and no ``integration_token`` has been set, this endpoint generates
    one and persists it so that the next ``GET /settings`` returns
    ``integration_token_is_set: True``.  The token itself is never echoed;
    the caller can retrieve it via ``PATCH /settings`` flow or from the
    Configuration UI (Step 12).
    """
    # Auto-generate the integration token when the HTTP channel is enabled
    # and no token exists yet.  This makes ``integration_token_is_set`` flip
    # to True on the first GET after enabling the channel, so HA users can
    # immediately see that a token is available.
    cfg = service.http_channel_config()
    if cfg.enabled and not cfg.integration_token:
        service.get_or_create_integration_token()
    return service.get_settings()


@router.patch("/settings", response_model=SettingsResponse)
def patch_settings(
    payload: SettingsUpdate,
    _ctx: Annotated[RequestContext, Depends(get_authenticated_context)],
    service: Annotated[SettingsService, Depends(_get_service)],
) -> SettingsResponse:
    """Apply a partial update to the reminders and channels configuration.

    Only fields explicitly supplied in the payload are changed; omitted
    fields are left at their current value.  Validation errors are handled
    by the existing ``RequestValidationError`` handler (→ ``validation.invalid_input``).

    To set a secret supply the new value; to clear it supply an explicit
    empty string (``""``) or ``null``.
    """
    return service.apply_update(payload)
