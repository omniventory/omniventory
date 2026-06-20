"""SQLAlchemy model for the NotificationDelivery table (M4 §3.6 / §9 Step 7).

A ``notification_delivery`` records one delivery attempt by an external channel
(email, http, mqtt) for a ``Notification`` row.

Design notes
------------
- ``notification_id`` FK → ``notifications.id`` with ``ondelete=CASCADE``:
  deleting a notification removes its delivery log.
- In-app delivery is implicit (the notification row existing is the proof);
  only external channel attempts produce delivery rows.
- Idempotency: a channel checks ``exists_sent(notification_id, channel)``
  before acting; a ``'failed'`` row may be retried on the next pass, but a
  ``'sent'`` row means "done — skip".
- ``detail`` stores a truncated error message on failure (up to 1024 chars);
  NULL on success.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class NotificationDelivery(Base):
    """A single external-channel delivery attempt for a notification.

    Columns
    -------
    id                  Auto-increment surrogate PK.
    notification_id     FK → notifications.id (CASCADE on delete).
    channel             Channel name: ``email`` / ``http`` / ``mqtt``.
    status              Outcome: ``sent`` / ``failed``.
    detail              Truncated error text on failure; NULL on success.
    created_at          Row-creation timestamp (DB server default).
    """

    __tablename__ = "notification_deliveries"

    __table_args__ = (
        # Index for idempotency lookups: "has this notification been sent on
        # this channel?" — used by exists_sent() in NotificationDeliveryRepository.
        Index(
            "ix_notification_deliveries_notification_channel",
            "notification_id",
            "channel",
            unique=False,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    notification_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "notifications.id",
            name="fk_notification_deliveries_notification_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(1024), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationship back to the parent notification (lazy; used when needed)
    notification: Mapped[Notification] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Notification",
        foreign_keys=[notification_id],
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"NotificationDelivery(id={self.id!r}, notification_id={self.notification_id!r}, "
            f"channel={self.channel!r}, status={self.status!r})"
        )
