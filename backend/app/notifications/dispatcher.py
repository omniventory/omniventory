"""NotificationDispatcher — channel routing for new notifications (M4 §4.6).

The dispatcher iterates the enabled channel adapters and delivers each new
notification.  In Step 3 the only implicit channel is **in-app** (the row
already exists in the DB).  External channels (Email, HTTP, MQTT) are wired in
Phase C steps (7–9) via the ``NotificationChannel`` protocol.

Architecture notes
------------------
- **In-app is implicit**: delivery = "the row exists."  No explicit action needed
  in the dispatcher for in-app.
- **Network I/O must happen after DB commit** (F1 fix, M4 §2): the caller
  (route handler or scheduled job) commits the DB session *first*, then calls
  ``build_dispatcher(db).dispatch()``.  The dispatcher receives already-committed
  ``Notification`` objects and performs I/O post-commit.  ``ReminderEngine``
  does NOT call dispatch itself — it returns new notifications to the caller via
  ``ScanSummary.new_notifications``.
- **Channel errors are best-effort**: a channel error is logged but never raised
  (it must not crash a scan or a movement).  Delivery rows are recorded in the
  ``notification_deliveries`` table (Step 7 §3.6).
- **Email is digest-only**: ``include_email_digest=True`` is set only by the
  daily scan; the event-trigger path passes ``False``.

``NotificationChannel`` protocol
---------------------------------
Each channel adapter implements:

    def deliver(
        self,
        notifications: list[Notification],
        *,
        include_email_digest: bool,
    ) -> None: ...

Phase C steps wire concrete adapters here.  The dispatcher collects all adapters
that are enabled (``adapter.is_enabled()``) and calls ``deliver``.  An adapter
that is not configured / disabled is a no-op.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.models.notification import Notification

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@runtime_checkable
class NotificationChannel(Protocol):
    """Protocol for pluggable notification channel adapters (M4 §4.6).

    Concrete implementations land in Steps 7–9 (email, http, mqtt).  Each
    adapter must be idempotent (skip notifications it already delivered) and
    must never raise (catch + log instead).
    """

    def is_enabled(self) -> bool:
        """Return True when this channel is configured and enabled."""
        ...  # pragma: no cover

    def deliver(
        self,
        notifications: list[Notification],
        *,
        include_email_digest: bool,
    ) -> None:
        """Deliver the given new notifications through this channel.

        Parameters
        ----------
        notifications:
            Newly created notification rows (already committed).
        include_email_digest:
            True on the daily-scan path; False on the event-trigger path.
            Email-only channels should send the digest only when this is True.
        """
        ...  # pragma: no cover


class NotificationDispatcher:
    """Iterates enabled channel adapters and delivers new notifications.

    Step 3: in-app is implicit (rows exist).  ``_channels`` is empty here;
    Phase C adapters register themselves via ``register_channel()``.

    Usage (caller's responsibility — after DB commit)
    -------------------------------------------------
    ::

        new_notifications = [...]  # already committed
        dispatcher = NotificationDispatcher()
        dispatcher.dispatch(new_notifications, include_email_digest=True)
    """

    def __init__(self) -> None:
        self._channels: list[NotificationChannel] = []

    def register_channel(self, channel: NotificationChannel) -> NotificationDispatcher:
        """Register an external channel adapter and return self for chaining."""
        self._channels.append(channel)
        return self

    def dispatch(
        self,
        notifications: list[Notification],
        *,
        include_email_digest: bool,
    ) -> None:
        """Deliver ``notifications`` through all enabled external channels.

        In-app delivery is implicit (the rows exist).  This method iterates
        external channel adapters.  Each adapter is called only when enabled;
        errors are caught, logged, and silenced (best-effort delivery).

        Parameters
        ----------
        notifications:
            Newly created ``Notification`` rows (already committed to DB).
        include_email_digest:
            Set to ``True`` on the daily-scan path so the email channel bundles
            a digest.  ``False`` on the event-trigger path (instant channels
            only; email waits for the next scan).
        """
        if not notifications:
            return

        for channel in self._channels:
            if not channel.is_enabled():
                continue
            try:
                channel.deliver(notifications, include_email_digest=include_email_digest)
            except Exception:
                logger.exception(
                    "Channel %s raised an error during dispatch; skipping.",
                    type(channel).__name__,
                )


def build_dispatcher(db: Session) -> NotificationDispatcher:
    """Build a ``NotificationDispatcher`` pre-registered with enabled channels.

    This factory is the canonical way for callers to obtain a dispatcher after
    committing a DB transaction.  It reads channel configuration from
    ``SettingsService`` and registers concrete adapters for every enabled
    channel.

    Currently registered channels (Steps 7–8):
    - ``EmailChannel``  — SMTP digest; registered unconditionally (the channel
      checks ``is_enabled()`` internally and is a no-op when disabled).
    - ``HttpChannel``   — instant outbound webhook; registered unconditionally
      (the channel checks ``is_enabled()`` internally and is a no-op when
      disabled or unconfigured).

    Future steps will add:
    - Step 9: ``MqttChannel`` (instant MQTT publish)

    Parameters
    ----------
    db:
        Active SQLAlchemy session passed to channel adapters (for settings
        reads and delivery-row writes).  The caller must commit notification
        rows *before* calling ``build_dispatcher(db).dispatch()``; delivery
        rows written by the channels are committed by the caller afterwards.

    Returns
    -------
    NotificationDispatcher
        A dispatcher with all currently-supported channels registered.
    """
    from app.notifications.channels.email import EmailChannel
    from app.notifications.channels.http import HttpChannel

    dispatcher = NotificationDispatcher()
    dispatcher.register_channel(EmailChannel(db))
    dispatcher.register_channel(HttpChannel(db))
    # Step 9: dispatcher.register_channel(MqttChannel(db))
    return dispatcher
