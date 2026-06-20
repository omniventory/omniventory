"""Integration state endpoint (M4 §4.9 / §4.10 / §9 Step 8).

Routes (under the api_prefix, e.g. /api):
    GET  /integrations/state   Return live inventory-state counts for Home
                                Assistant's RESTful sensor.  **Not** behind the
                                session-cookie dependency — HA cannot hold a
                                session cookie.

Authentication
--------------
The endpoint is guarded by a **static integration token**, NOT the session
cookie.  The token is read from:
  - ``X-Omniventory-Token`` request header, OR
  - ``?token=`` query parameter.

It is compared to ``channels.http.integration_token`` stored in the settings
KV table.  A missing or wrong token returns 401 ``integration.invalid_token``.

A dedicated FastAPI dependency (``_verify_integration_token``) handles the
token check so the route handler stays clean.

Error contract:
    401  Missing or invalid integration token → ``integration.invalid_token``.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode, ErrorResponse
from app.db.session import get_db
from app.schemas.integration import IntegrationStateResponse
from app.services.integration_state import IntegrationStateService
from app.services.settings import SettingsService

logger = logging.getLogger(__name__)

_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
}

router = APIRouter(prefix="/integrations", tags=["integrations"], responses=_ERROR_RESPONSES)


# ---------------------------------------------------------------------------
# Token auth dependency (independent of session cookie)
# ---------------------------------------------------------------------------


def _verify_integration_token(
    db: Annotated[Session, Depends(get_db)],
    x_omniventory_token: Annotated[str | None, Header(alias="X-Omniventory-Token")] = None,
    token: Annotated[str | None, Query()] = None,
) -> None:
    """Verify the integration token from the header or query parameter.

    Reads the token from (in order of precedence):
    1. ``X-Omniventory-Token`` HTTP header.
    2. ``?token=`` query parameter.

    Compares the provided token to the value stored in
    ``channels.http.integration_token``.  Raises 401
    ``integration.invalid_token`` if:
    - No token is provided (header and query param both absent), OR
    - The provided token does not match the stored token, OR
    - No integration token has been configured yet.

    This dependency is intentionally **separate** from
    ``get_authenticated_context`` so that the state endpoint is reachable by
    Home Assistant without a session cookie.

    Raises
    ------
    AppError(integration.invalid_token, 401)
        When the provided token is missing or wrong.
    """
    provided_token = x_omniventory_token or token
    if not provided_token:
        raise AppError(ErrorCode.INTEGRATION_INVALID_TOKEN, status_code=401)

    settings = SettingsService(db)
    cfg = settings.http_channel_config()
    stored_token = cfg.integration_token

    if not stored_token or provided_token != stored_token:
        raise AppError(ErrorCode.INTEGRATION_INVALID_TOKEN, status_code=401)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get(
    "/state",
    response_model=IntegrationStateResponse,
    dependencies=[Depends(_verify_integration_token)],
)
def get_integration_state(
    db: Annotated[Session, Depends(get_db)],
) -> IntegrationStateResponse:
    """Return live inventory-state counts for Home Assistant's RESTful sensor.

    Computes the current:
    - ``low_stock_count``  — definitions below their low-stock threshold.
    - ``expiring_count``   — lots expiring within the best-before lead window.
    - ``expired_count``    — lots that have already expired.
    - ``generated_at``     — UTC ISO-8601 timestamp (not cached).

    Requires a valid ``integration_token`` in the ``X-Omniventory-Token``
    header or ``?token=`` query parameter.  Returns 401
    ``integration.invalid_token`` for missing or wrong tokens.

    This endpoint is **not** behind the session-cookie dependency.  Home
    Assistant's RESTful sensor configuration points at this URL with the
    token in a header or query parameter.
    """
    result = IntegrationStateService(db).compute()
    return IntegrationStateResponse(**result)
