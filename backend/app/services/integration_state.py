"""Integration state service — live counts for the Home Assistant RESTful sensor (M4 §4.9).

``IntegrationStateService`` computes the live inventory state counts consumed
by ``GET /api/integrations/state``.

Architecture
------------
- **Pure read** (like ``LowStockService`` and ``ExpiryService``): no writes,
  no persistence.  Computed fresh on every request.
- **Reuses existing services**: delegates to ``LowStockService.compute()``
  for ``low_stock_count`` and ``ExpiryService.compute(within_days)`` for the
  expiry counts.  **No re-implementation of any rule.**
- **Expiry horizon**: uses ``SettingsService.best_before_lead_days()`` (the
  global best-before lead) as the ``within_days`` parameter.  This makes the
  "expiring" window consistent with what the reminder engine uses — items that
  are within the alert window appear as expiring here too.  The per-item and
  per-user lead overrides are not applied here (the endpoint is a summary for
  external consumers; precise per-item resolution is for the reminder engine).
- **``generated_at``**: returns the current UTC time as an ISO-8601 string.
  UTC is chosen over household-local time because external consumers (Home
  Assistant) typically work in UTC and can convert as needed.  A note is
  included here for future maintainers.

All DB access goes through repository-backed services; no raw queries here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

from sqlalchemy.orm import Session

from app.services.expiry import ExpiryService
from app.services.low_stock import LowStockService
from app.services.settings import SettingsService


class IntegrationStateDict(TypedDict):
    """Typed result from ``IntegrationStateService.compute()``."""

    low_stock_count: int
    expiring_count: int
    expired_count: int
    generated_at: str


class IntegrationStateService:
    """Compute live inventory-state counts for the HA RESTful sensor endpoint.

    Instantiate with a DB session; call ``compute()`` to get the result.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def compute(self) -> IntegrationStateDict:
        """Return the live state counts as a plain dict.

        Returns
        -------
        dict with keys:
            ``low_stock_count``  — number of definitions currently below their
                                   low-stock threshold (from ``LowStockService``).
            ``expiring_count``   — number of lots expiring within the
                                   best-before lead window but not yet expired
                                   (``status == "expiring"``).
            ``expired_count``    — number of lots that have already passed their
                                   best-before date (``status == "expired"``).
            ``generated_at``     — current UTC time in ISO-8601 format.
                                   UTC is used (not household-local) because HA
                                   and other external consumers typically expect
                                   UTC timestamps.
        """
        # Low-stock count: total definitions currently below threshold.
        low_stock_items = LowStockService(self._db).compute()
        low_stock_count = len(low_stock_items)

        # Expiry counts: use the global best-before lead as the horizon window.
        # Per-item / per-user lead overrides are not applied here — this is a
        # summary endpoint, not the full reminder engine.
        lead_days = SettingsService(self._db).best_before_lead_days()
        expiry_items = ExpiryService(self._db).compute(within_days=lead_days)
        expiring_count = sum(1 for item in expiry_items if item.status == "expiring")
        expired_count = sum(1 for item in expiry_items if item.status == "expired")

        # generated_at: current UTC ISO-8601 timestamp.
        generated_at = datetime.now(UTC).isoformat()

        return {
            "low_stock_count": low_stock_count,
            "expiring_count": expiring_count,
            "expired_count": expired_count,
            "generated_at": generated_at,
        }
