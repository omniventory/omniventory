"""Repository for the NotificationDelivery table (M4 §4.1 / §9 Step 7).

All DB access to the ``notification_deliveries`` table goes through this class.
Route handlers and services must not issue raw queries against the table;
they call ``NotificationDeliveryRepository`` methods.

Public methods
--------------
``record(notification_id, channel, status, detail=None)``
    Insert a delivery row.  Always inserts a new row (not idempotent itself —
    callers control when to call it, after checking ``exists_sent``).

``exists_sent(notification_id, channel) -> bool``
    Return True when there is at least one ``status='sent'`` row for this
    (notification_id, channel) pair.  Used by channel adapters to skip
    already-delivered notifications (idempotency gate).  A ``'failed'`` row
    does NOT block re-delivery; failed rows may be retried on the next pass.
"""

from __future__ import annotations

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models.notification_delivery import NotificationDelivery


class NotificationDeliveryRepository:
    """Data-access object for the notification_deliveries table."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def record(
        self,
        notification_id: int,
        channel: str,
        status: str,
        detail: str | None = None,
    ) -> NotificationDelivery:
        """Insert a delivery row and flush (does not commit).

        Parameters
        ----------
        notification_id:
            FK → notifications.id of the notification that was delivered.
        channel:
            Channel name: ``'email'`` / ``'http'`` / ``'mqtt'``.
        status:
            Outcome: ``'sent'`` on success, ``'failed'`` on error.
        detail:
            Optional error text (truncated to 1024 chars) on failure.
            Pass ``None`` on success.

        Returns
        -------
        NotificationDelivery
            The freshly inserted (and flushed) row.
        """
        detail_truncated = detail[:1024] if detail else None
        row = NotificationDelivery(
            notification_id=notification_id,
            channel=channel,
            status=status,
            detail=detail_truncated,
        )
        self._db.add(row)
        self._db.flush()
        return row

    def exists_sent(self, notification_id: int, channel: str) -> bool:
        """Return True if a ``'sent'`` delivery row exists for (notification_id, channel).

        A ``'failed'`` row does NOT prevent re-delivery; only a ``'sent'`` row
        means "done — skip this notification on this channel".

        Parameters
        ----------
        notification_id:
            The notification to check.
        channel:
            The channel to check (e.g. ``'email'``).

        Returns
        -------
        bool
            True when at least one ``status='sent'`` row exists.
        """
        stmt = select(
            exists().where(
                NotificationDelivery.notification_id == notification_id,
                NotificationDelivery.channel == channel,
                NotificationDelivery.status == "sent",
            )
        )
        return bool(self._db.execute(stmt).scalar())
