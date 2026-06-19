"""Repository for the Notification table (M4 §4.1 / §9 Step 3).

All DB access to the ``notifications`` table goes through this class.  Route
handlers and services must not issue raw queries against ``notifications``; they
call ``NotificationRepository`` methods.

Public methods (Step 3 scope)
-----------------------------
``create_if_absent(...)``
    Idempotent insert by ``(user_id, dedup_key)``.  Returns the
    ``(Notification, created: bool)`` tuple — ``created=True`` when a new row
    was inserted, ``False`` when a matching row already existed.

    Implementation strategy: SELECT first, INSERT on miss.  The unique index
    ``uq_notifications_user_dedup`` provides DB-level idempotency as a backstop
    (single worker; idempotent scan; no complex concurrency handling needed per
    §2 "one engine, source-pluggable" locked decision).

Step 4 will add: ``open_low_stock_opener``, ``open_low_stock_openers``,
                  ``mark_resolved``.
Step 6 will add: ``list_for_user``, ``unread_count``, ``mark_read``,
                  ``mark_all_read``.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.notification import Notification


class NotificationRepository:
    """Data-access object for the notifications table."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ---------------------------------------------------------------------- #
    # Write                                                                    #
    # ---------------------------------------------------------------------- #

    def create_if_absent(
        self,
        *,
        user_id: int,
        source: str,
        subject_type: str,
        subject_id: int,
        dedup_key: str,
        message_code: str,
        params: dict[str, Any] | None = None,
        # Low-stock episode fields (Step 4) — unused in Step 3 callers but
        # accepted here so the signature is stable.
        episode_started_on: date | None = None,
        offset_days: int | None = None,
    ) -> tuple[Notification, bool]:
        """Insert a notification row only when the dedup key is absent for this user.

        Returns
        -------
        (notification, created)
            ``created=True``  → a new row was inserted and flushed.
            ``created=False`` → an existing row with this dedup key was returned
                               unchanged (the scan is idempotent).

        Implementation
        --------------
        SELECT → miss → INSERT + flush.  The unique index
        ``uq_notifications_user_dedup`` provides DB-level idempotency as a
        backstop for any concurrent edge case (single worker, so unlikely).
        """
        # SELECT first — the common case after the first scan is a hit.
        existing = self._get_by_dedup(user_id, dedup_key)
        if existing is not None:
            return existing, False

        # INSERT
        params_text: str | None = json.dumps(params) if params is not None else None
        notification = Notification(
            user_id=user_id,
            source=source,
            subject_type=subject_type,
            subject_id=subject_id,
            dedup_key=dedup_key,
            message_code=message_code,
            params=params_text,
            episode_started_on=episode_started_on,
            offset_days=offset_days,
        )
        try:
            self._db.add(notification)
            self._db.flush()
            return notification, True
        except IntegrityError:
            # Race condition guard: another concurrent call sneaked in an
            # identical dedup key between our SELECT and INSERT.  Roll back the
            # sub-transaction, re-fetch, and return the existing row.
            self._db.rollback()
            existing = self._get_by_dedup(user_id, dedup_key)
            if existing is not None:
                return existing, False
            raise  # Unexpected integrity error — re-raise.

    # ---------------------------------------------------------------------- #
    # Read (internal helpers)                                                  #
    # ---------------------------------------------------------------------- #

    def _get_by_dedup(self, user_id: int, dedup_key: str) -> Notification | None:
        """Return an existing notification by ``(user_id, dedup_key)``, or None."""
        stmt = select(Notification).where(
            Notification.user_id == user_id,
            Notification.dedup_key == dedup_key,
        )
        return self._db.execute(stmt).scalar_one_or_none()
