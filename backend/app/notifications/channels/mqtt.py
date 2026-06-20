"""MQTT instant notification channel adapter (M4 §4.8 / §9 Step 9).

``MqttChannel`` implements the ``NotificationChannel`` protocol for publishing
each new reminder notification to the broker via the process-level
``MqttBridge`` singleton.

Architecture
------------
- **Instant channel**: fires for every new notification on both the daily-scan
  and event-trigger paths.  The ``include_email_digest`` flag is intentionally
  ignored — MQTT is an instant channel, not a digest channel.
- **Payload** per notification::

      {"code": <message_code>, "params": <params dict>, "message": <rendered text>}

  Published to ``{prefix}/notifications/{source}`` with ``retained=False``.
- **Message rendering**: ``render_line()`` is called with the recipient's
  ``preferred_language`` (falls back to ``'en'``).
- **Idempotency**: ``exists_sent(nid, 'mqtt')`` is checked before publishing;
  already-delivered notifications are skipped.
- **Best-effort**: all errors (bridge not connected, publish failure) are
  caught, logged, and recorded as ``status='failed'``; they are never
  propagated.

Configuration
-------------
The channel is considered **enabled** when:
1. ``channels.mqtt.enabled`` is True, AND
2. The ``MqttBridge`` singleton ``is_connected``.

If either condition fails, ``deliver()`` is a complete no-op.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.notifications.messages import render_line
from app.notifications.mqtt import get_mqtt_bridge
from app.repositories.notification_delivery import NotificationDeliveryRepository
from app.repositories.user import UserRepository
from app.services.settings import SettingsService

if TYPE_CHECKING:
    from app.models.notification import Notification

logger = logging.getLogger(__name__)

# Sentinel string for the delivery channel name (M4 §3.6).
_CHANNEL_NAME = "mqtt"


class MqttChannel:
    """Instant MQTT notification channel adapter (implements ``NotificationChannel``).

    Parameters
    ----------
    db:
        Active SQLAlchemy session.  Used to read settings, look up recipients,
        and record delivery rows.  Must outlive this channel instance.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._settings = SettingsService(db)
        self._user_repo = UserRepository(db)
        self._delivery_repo = NotificationDeliveryRepository(db)

    # ------------------------------------------------------------------
    # NotificationChannel protocol
    # ------------------------------------------------------------------

    def is_enabled(self) -> bool:
        """Return True when the MQTT channel is enabled and the bridge is connected.

        The channel is enabled when:
        1. ``channels.mqtt.enabled`` is True, AND
        2. The process-level ``MqttBridge`` singleton ``is_connected``.

        If either condition fails the channel is disabled and ``deliver()`` is a
        complete no-op.
        """
        cfg = self._settings.mqtt_channel_config()
        if not cfg.enabled:
            return False
        return get_mqtt_bridge().is_connected

    def deliver(
        self,
        notifications: list[Notification],
        *,
        include_email_digest: bool,  # noqa: ARG002 — ignored; MQTT is instant
    ) -> None:
        """Publish each new notification to the broker.

        This channel is **instant** — ``include_email_digest`` is ignored.
        Every notification in ``notifications`` that has not already been
        delivered via MQTT is published individually.

        Per-notification flow:
        1. Check ``exists_sent(nid, 'mqtt')`` — skip if already delivered.
        2. Look up the recipient's preferred language.
        3. Render the human-readable ``message`` via the server catalog.
        4. Publish via ``MqttBridge.publish_notification()``.
        5. Record one ``notification_deliveries`` row (``sent`` / ``failed``).

        Errors are caught per-notification; a failure on one does not skip
        subsequent notifications.

        Parameters
        ----------
        notifications:
            List of newly committed ``Notification`` rows to deliver.
        include_email_digest:
            Ignored — MQTT is an instant channel, not a digest channel.
        """
        if not notifications:
            return

        bridge = get_mqtt_bridge()
        if not bridge.is_connected:
            return

        for notification in notifications:
            self._deliver_one(notification, bridge)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _deliver_one(self, notification: Notification, bridge: object) -> None:
        """Publish a single notification to the broker.

        Checks idempotency, renders the payload, publishes, and records the
        delivery outcome.  Catches all errors (best-effort).
        """
        from app.notifications.mqtt import MqttBridge

        assert isinstance(bridge, MqttBridge)  # type narrowing for mypy

        nid = notification.id

        # Idempotency: skip notifications already successfully delivered.
        if self._delivery_repo.exists_sent(nid, _CHANNEL_NAME):
            return

        try:
            # Look up the recipient's preferred language for message rendering.
            user = self._user_repo.get_by_id(notification.user_id)
            lang = (user.preferred_language if user else None) or "en"

            # Render the human-readable message from the server catalog.
            params: dict[str, object] = {}
            if notification.params:
                try:
                    params = json.loads(notification.params)
                except (ValueError, TypeError):
                    params = {}

            message = render_line(notification.message_code, params, lang)

            # Publish to the broker via the bridge.
            bridge.publish_notification(notification, message)

            # Record success.
            self._delivery_repo.record(
                notification_id=nid,
                channel=_CHANNEL_NAME,
                status="sent",
            )
            logger.info(
                "MqttChannel: notification_id=%d published (source=%s).",
                nid,
                notification.source,
            )

        except Exception as exc:
            # Best-effort: record failure, log, continue.
            detail = str(exc)
            logger.warning(
                "MqttChannel: failed to publish notification_id=%d: %s",
                nid,
                detail,
            )
            try:
                self._delivery_repo.record(
                    notification_id=nid,
                    channel=_CHANNEL_NAME,
                    status="failed",
                    detail=detail,
                )
            except Exception:
                logger.exception(
                    "MqttChannel: could not record 'failed' delivery for notification_id=%s",
                    nid,
                )
