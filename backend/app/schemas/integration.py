"""Schemas for the integration state endpoint (M4 §4.11 / §9 Step 8).

``IntegrationStateResponse``
    Returned by ``GET /api/integrations/state``.  Provides live inventory-state
    counts for Home Assistant's RESTful sensor to poll.

Fields
------
low_stock_count     int     Number of definitions currently below their low-stock
                            threshold.
expiring_count      int     Number of lots expiring within the best-before lead
                            window (status == "expiring").
expired_count       int     Number of lots that have already passed their
                            best-before date (status == "expired").
generated_at        str     UTC ISO-8601 timestamp of when the response was
                            computed (not cached).
"""

from __future__ import annotations

from pydantic import BaseModel


class IntegrationStateResponse(BaseModel):
    """Live inventory-state counts for the Home Assistant RESTful sensor.

    Authorised by the ``integration_token`` (header or query param) — not the
    session cookie.  See ``GET /api/integrations/state``.
    """

    low_stock_count: int
    expiring_count: int
    expired_count: int
    generated_at: str  # UTC ISO-8601 string
