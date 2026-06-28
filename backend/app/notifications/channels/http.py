"""HTTP outbound webhook channel adapter (M4 §4.9 / §9 Step 8).

``HttpChannel`` implements the ``NotificationChannel`` protocol for POSTing
each new notification to a configured webhook URL via ``httpx``.

Architecture
------------
- **Instant channel**: the channel fires for every new notification, on both
  the daily-scan path and the event-trigger path.  The
  ``include_email_digest`` flag is intentionally ignored — HTTP is instant,
  not digest-only.
- **Payload**: ``{"code": ..., "params": ..., "message": ...}``
  - ``code``    — ``message_code`` string (e.g. ``"reminder.best_before"``).
  - ``params``  — decoded params dict (from ``json.loads(notification.params)``).
  - ``message`` — human-readable text rendered by the server catalog
                  (``app/notifications/messages.py``) in the recipient's
                  ``preferred_language`` (falls back to ``"en"``).
- **Auth header convention**: when ``channels.http.auth_header`` is set it is
  sent as the full value of the ``Authorization`` HTTP header.  This covers
  the most common cases: ``"Bearer <token>"``, ``"Token <token>"``, or a
  raw API key.  Callers who need a custom header name should include it in
  the ``auth_header`` setting value as ``"HeaderName: value"`` — but the
  simple convention here is ``Authorization: <auth_header value>``.  This
  choice is documented in the implementation brief.
- **Idempotency**: ``exists_sent(nid, 'http')`` is checked before posting;
  already-delivered notifications are skipped.  Each notification gets its
  own delivery row (``status='sent'`` / ``'failed'``).
- **Best-effort**: network/rendering errors are caught, logged, and recorded
  as ``status='failed'``; they are never propagated.
- **Basic SSRF sanity** (M4 §12 / §4.9): the webhook URL must have an
  ``http`` or ``https`` scheme.  Full SSRF protection (private-IP blocking,
  redirects, DNS rebinding) is deferred to M6 (roadmap §5 M6).

Configuration (all via ``SettingsService``)
-------------------------------------------
- ``channels.http.enabled``          — master on/off switch.
- ``channels.http.webhook_url``      — destination URL (required for enable).
- ``channels.http.auth_header``      — optional auth value sent as the
                                       ``Authorization`` header.

The channel is considered **enabled** when ``enabled=True`` AND
``webhook_url`` is non-empty AND passes the basic SSRF sanity check.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.notifications.messages import render_line
from app.repositories.notification_delivery import NotificationDeliveryRepository
from app.repositories.user import UserRepository
from app.services.settings import SettingsService

if TYPE_CHECKING:
    from app.models.notification import Notification

logger = logging.getLogger(__name__)

# Sentinel string for the delivery channel name (M4 §3.6).
_CHANNEL_NAME = "http"

# Outbound POST timeout in seconds (short, as specified in §4.9).
_TIMEOUT_SECONDS = 5.0

# Allowed URL schemes for the outbound webhook (basic SSRF sanity — §12).
_ALLOWED_SCHEMES = {"http", "https"}


def _is_safe_url(url: str) -> bool:
    """Basic public-URL sanity check (M4 §4.9 / §12).

    Checks that the URL has an http or https scheme.  This is intentionally
    minimal — full SSRF protection (blocking private IP ranges, following
    redirects, DNS rebinding defence) is deferred to M6 (roadmap §5 M6).
    """
    try:
        parsed = urlparse(url)
        return parsed.scheme in _ALLOWED_SCHEMES and bool(parsed.netloc)
    except Exception:
        return False


class HttpChannel:
    """Outbound webhook channel adapter (implements ``NotificationChannel``).

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
        """Return True when the HTTP channel is enabled, configured, and the
        webhook URL passes the basic SSRF sanity check.

        The channel is enabled when:
        1. ``channels.http.enabled`` is True, AND
        2. ``channels.http.webhook_url`` is non-empty, AND
        3. The webhook URL has an ``http`` or ``https`` scheme and a host.

        If any condition fails the channel is disabled and ``deliver()`` is a
        complete no-op.
        """
        cfg = self._settings.http_channel_config()
        if not cfg.enabled:
            return False
        if not cfg.webhook_url:
            return False
        # Basic SSRF sanity — full guard is M6.
        return _is_safe_url(cfg.webhook_url)

    def deliver(
        self,
        notifications: list[Notification],
        *,
        include_email_digest: bool,  # noqa: ARG002 — ignored; HTTP is instant
    ) -> None:
        """POST each new notification to the configured webhook URL.

        This channel is **instant** — ``include_email_digest`` is ignored.
        Every notification in ``notifications`` that has not already been
        delivered via HTTP is POSTed individually.

        Per-notification flow:
        1. Check ``exists_sent(nid, 'http')`` — skip if already delivered.
        2. Look up the recipient's preferred language.
        3. Decode ``notification.params`` to a dict.
        4. Render the human-readable ``message`` via the server catalog.
        5. POST ``{code, params, message}`` to the webhook URL with a short
           timeout and optional ``Authorization`` header.
        6. Record one ``notification_deliveries`` row (``sent`` / ``failed``).

        Errors are caught per-notification; a failure on one does not skip
        subsequent notifications.

        Parameters
        ----------
        notifications:
            List of newly committed ``Notification`` rows to deliver.
        include_email_digest:
            Ignored — HTTP is an instant channel, not a digest channel.
        """
        if not notifications:
            return

        cfg = self._settings.http_channel_config()
        # Guard: re-check enabled status (callers should also check, but be safe).
        if not cfg.enabled or not cfg.webhook_url or not _is_safe_url(cfg.webhook_url):
            return

        webhook_url: str = cfg.webhook_url
        auth_header: str | None = cfg.auth_header

        for notification in notifications:
            self._deliver_one(notification, webhook_url, auth_header)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _deliver_one(
        self,
        notification: Notification,
        webhook_url: str,
        auth_header: str | None,
    ) -> None:
        """POST a single notification to the webhook URL.

        Checks idempotency, renders the payload, POSTs, and records the
        delivery outcome.  Catches all errors (best-effort).
        """
        nid = notification.id

        # Idempotency: skip notifications already successfully delivered.
        if self._delivery_repo.exists_sent(nid, _CHANNEL_NAME):
            return

        try:
            # Look up the recipient's preferred language for message rendering.
            user = self._user_repo.get_by_id(notification.user_id)
            lang = (user.preferred_language if user else None) or "en"

            # Decode params JSON blob.
            params: dict[str, object] = {}
            if notification.params:
                try:
                    params = json.loads(notification.params)
                except (ValueError, TypeError):
                    params = {}

            # Render the human-readable message from the server catalog.
            message = render_line(notification.message_code, params, lang)

            # Build the payload (§4.9: {code, params, message}).
            payload = {
                "code": notification.message_code,
                "params": params,
                "message": message,
            }

            # Build request headers.
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if auth_header:
                # Convention: auth_header value is sent verbatim as the
                # Authorization header (e.g. "Bearer <token>", "Token <key>").
                # Callers who need a custom header name can prefix with
                # "HeaderName: value", but the default is Authorization.
                headers["Authorization"] = auth_header

            # SSRF guard — reject unsafe URLs before any network connection.
            # UnsafeUrlError is a ValueError → caught by the except Exception
            # below and recorded as a failed delivery (best-effort).
            from app.core.net_guard import validate_outbound_url

            validate_outbound_url(webhook_url)

            # POST with a short timeout (§4.9: short timeout, e.g. 5 s).
            # ``follow_redirects=False`` prevents a 302→internal SSRF bypass.
            with httpx.Client(timeout=_TIMEOUT_SECONDS, follow_redirects=False) as client:
                response = client.post(webhook_url, json=payload, headers=headers)
                # Raise for 4xx/5xx so they land in the except block as failures.
                response.raise_for_status()

            # Record success.
            self._delivery_repo.record(
                notification_id=nid,
                channel=_CHANNEL_NAME,
                status="sent",
            )
            logger.info(
                "HttpChannel: notification_id=%d posted to %s (HTTP %d).",
                nid,
                webhook_url,
                response.status_code,
            )

        except Exception as exc:
            # Best-effort: record failure, log, continue.
            detail = str(exc)
            logger.warning(
                "HttpChannel: failed to post notification_id=%d to %s: %s",
                nid,
                webhook_url,
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
                    "HttpChannel: could not record 'failed' delivery for notification_id=%s",
                    nid,
                )
