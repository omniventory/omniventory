"""Expiry computed scan service (M3 §4.4).

``ExpiryService`` is a pure-read service — it never writes to the DB.
It queries all lots whose ``best_before_date`` falls within the requested
horizon and tags each with ``status`` and ``days_remaining``.

Expiry rules (M3 §4.4 / §2 decisions):
    A lot is included iff:
        - it has a ``best_before_date`` (NOT NULL), AND
        - ``best_before_date <= today + within_days`` (expired ∪ expiring), AND
        - the lot is not a depleted ``exact`` lot (quantity IS NULL OR quantity > 0).

    For each qualifying lot:
        days_remaining = (best_before_date - today).days
        status = 'expired'  if days_remaining < 0
               = 'expiring'  otherwise  (0 = expires today, positive = future)

    Ordering: soonest/most-overdue first (expired naturally leads because their
    date is earliest).

    ``within_days`` is clamped to >= 0 — never rejected.  ``within_days=0``
    returns only already-expired + expiring-today lots.  Negative values are
    clamped to 0.

``Decimal`` is used for quantity; never float (roadmap §2.9).
``date`` is used for the best-before date; never datetime (roadmap §2.9).

All DB access goes through repositories; no raw queries in this layer.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.repositories.stock_instance import StockInstanceRepository
from app.schemas.expiry import ExpiringItem


class ExpiryService:
    """Pure-read service that computes the current expiring/expired lot list.

    Instantiate with a DB session; call ``compute(within_days)`` to get the
    result.  No writes, no persistence — the result is computed on every
    request.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._inst_repo = StockInstanceRepository(db)

    def compute(self, within_days: int) -> list[ExpiringItem]:
        """Return lots expiring within ``within_days`` days from today (inclusive).

        The returned set is ``expired ∪ expiring-within-N``:
        - ``within_days`` is clamped to ``>= 0`` (never rejected).
        - ``cutoff = today + timedelta(days=within_days)``
        - Lots with ``best_before_date <= cutoff`` AND ``(quantity IS NULL OR
          quantity > 0)`` AND ``best_before_date IS NOT NULL`` are returned.
        - Each lot is tagged:
            ``days_remaining = (best_before_date - today).days``
            ``status = 'expired'`` if ``days_remaining < 0`` else ``'expiring'``
        - Ordering: soonest-first (expired leads naturally).

        Pure read — does NOT write to the DB.
        """
        within_days = max(within_days, 0)  # clamp; negative treated as 0
        today = date.today()
        cutoff = today + timedelta(days=within_days)

        lots = self._inst_repo.list_expiring(cutoff)

        results: list[ExpiringItem] = []
        for lot in lots:
            days_remaining = (lot.best_before_date - today).days  # type: ignore[operator]
            results.append(
                ExpiringItem(
                    instance_id=lot.id,
                    definition_id=lot.definition_id,
                    name=lot.definition.name,
                    location_id=lot.location_id,
                    best_before_date=lot.best_before_date,  # type: ignore[arg-type]
                    quantity=lot.quantity,
                    days_remaining=days_remaining,
                    status="expired" if days_remaining < 0 else "expiring",
                )
            )

        return results
