"""MQTT bridge — process-level singleton for the Home Assistant paho-mqtt connection (M4 §4.8 / §9 Step 9).

Architecture
------------
``MqttBridge`` manages a single long-lived paho-mqtt connection owned by the
FastAPI lifespan.  It is started when ``channels.mqtt.enabled`` is True and
the environment is not ``test``; it is stopped cleanly on application shutdown.

paho's ``loop_start()`` runs a background thread that handles reconnection
automatically — the bridge is passive after ``start()`` returns.

Process-level singleton
-----------------------
``get_mqtt_bridge()`` returns the module-level ``_bridge`` singleton so that
both the lifespan (start/stop) and any call site (scheduler job, route handler)
can reach the same instance without dependency injection.  The singleton is
replaced on each ``start()`` call (idempotent for the lifespan pattern).

Topic conventions (all configurable via ``channels.mqtt.topic_prefix``)
-----------------------------------------------------------------------
Reminder publish (instant, retained=False)::

    {prefix}/notifications/{source}
    payload: {"code": ..., "params": ..., "message": ...}

State topics (retained=True — HA sees last value on reconnect)::

    {prefix}/state/low_stock_count    integer value
    {prefix}/state/expiring_count     integer value
    {prefix}/state/expired_count      integer value

Home Assistant MQTT discovery (gated by ``discovery_enabled``)::

    homeassistant/sensor/omniventory_{metric}/config
    payload: HA-spec discovery JSON config

Best-effort
-----------
All publish and connect errors are caught, logged, and silenced.  A bridge
error must never crash a scan, a movement handler, or any other application
path.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.notification import Notification

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HA discovery config helpers
# ---------------------------------------------------------------------------

# The three state metrics and their Human-readable names.
_STATE_METRICS: list[tuple[str, str]] = [
    ("low_stock_count", "Low Stock Count"),
    ("expiring_count", "Expiring Count"),
    ("expired_count", "Expired Count"),
]


def _discovery_payload(metric: str, name: str, state_topic: str) -> dict[str, Any]:
    """Build a Home Assistant MQTT discovery payload for a single sensor.

    The payload follows the HA MQTT sensor discovery spec:
    https://www.home-assistant.io/integrations/sensor.mqtt/
    """
    return {
        "name": f"Omniventory {name}",
        "unique_id": f"omniventory_{metric}",
        "state_topic": state_topic,
        "icon": "mdi:package-variant",
        "value_template": "{{ value }}",
    }


# ---------------------------------------------------------------------------
# MqttChannelConfig (bridge-internal config snapshot)
# ---------------------------------------------------------------------------


@dataclass
class MqttBridgeConfig:
    """Snapshot of MQTT channel settings consumed by ``MqttBridge.start()``."""

    host: str
    port: int
    topic_prefix: str
    username: str | None = None
    password: str | None = None  # noqa: S105 — internal, never serialised
    use_tls: bool = False
    discovery_enabled: bool = False


# ---------------------------------------------------------------------------
# MqttBridge
# ---------------------------------------------------------------------------


class MqttBridge:
    """paho-mqtt long-lived connection manager (process-level singleton).

    Lifecycle
    ---------
    1. ``start(config)`` — connect to the broker, start the paho background
       thread, and (if ``discovery_enabled``) publish HA discovery configs.
    2. Application serves requests; ``publish_notification`` / ``publish_state``
       are called best-effort from channel adapters and dispatch points.
    3. ``stop()`` — disconnect cleanly; paho background thread exits.

    The bridge exposes ``is_connected`` so callers can guard publish calls
    without importing paho themselves.
    """

    def __init__(self) -> None:
        self._client: Any = None  # paho.mqtt.client.Client | None
        self._config: MqttBridgeConfig | None = None
        self._connected = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, config: MqttBridgeConfig) -> None:
        """Connect to the broker and start the paho background thread.

        Parameters
        ----------
        config:
            Connection parameters read from ``SettingsService``.

        Notes
        -----
        paho's ``loop_start()`` spawns a daemon thread that handles
        PING/ACK and automatic reconnection.  This method returns as soon
        as ``connect()`` completes (or raises); the thread keeps running.

        On connect callback (``on_connect``) we publish HA discovery
        configs when ``config.discovery_enabled`` is True.
        """
        import paho.mqtt.client as mqtt

        with self._lock:
            self._config = config
            client_id = "omniventory"
            client = mqtt.Client(client_id=client_id)

            if config.username:
                client.username_pw_set(config.username, config.password)

            if config.use_tls:
                client.tls_set()

            bridge_ref = self  # capture self for the callback

            def on_connect(
                _client: Any,
                _userdata: Any,
                _flags: Any,
                rc: int,
            ) -> None:
                if rc == 0:
                    with bridge_ref._lock:
                        bridge_ref._connected = True
                    logger.info("MqttBridge: connected to broker.")
                    if config.discovery_enabled:
                        bridge_ref._publish_discovery_unsafe(client, config.topic_prefix)
                else:
                    logger.warning("MqttBridge: connection failed (rc=%d).", rc)

            def on_disconnect(_client: Any, _userdata: Any, rc: int) -> None:
                with bridge_ref._lock:
                    bridge_ref._connected = False
                if rc != 0:
                    logger.warning(
                        "MqttBridge: unexpected disconnect (rc=%d); paho will reconnect.", rc
                    )
                else:
                    logger.info("MqttBridge: disconnected cleanly.")

            client.on_connect = on_connect
            client.on_disconnect = on_disconnect

            try:
                client.connect(config.host, config.port)
                client.loop_start()
                self._client = client
            except Exception:
                logger.exception(
                    "MqttBridge: failed to connect to %s:%d — MQTT disabled for this session.",
                    config.host,
                    config.port,
                )
                self._client = None
                self._connected = False

    def stop(self) -> None:
        """Stop the background thread and disconnect from the broker cleanly."""
        with self._lock:
            client = self._client
            self._client = None
            self._connected = False

        if client is not None:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                logger.exception("MqttBridge: error during stop — ignoring.")

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """True when the broker connection is established."""
        with self._lock:
            return self._connected

    # ------------------------------------------------------------------
    # Publish helpers
    # ------------------------------------------------------------------

    def publish_notification(self, notification: Notification, message: str) -> None:
        """Publish a reminder notification event to ``{prefix}/notifications/{source}``.

        Parameters
        ----------
        notification:
            The committed ``Notification`` row.
        message:
            Pre-rendered human-readable text (from ``render_line``).

        Payload
        -------
        ``{"code": <message_code>, "params": <params dict>, "message": <message>}``
        ``retained=False`` — reminder events are ephemeral.
        """
        client, prefix = self._get_client_and_prefix()
        if client is None:
            return

        params: dict[str, object] = {}
        if notification.params:
            try:
                params = json.loads(notification.params)
            except (ValueError, TypeError):
                params = {}

        topic = f"{prefix}/notifications/{notification.source}"
        payload = json.dumps(
            {
                "code": notification.message_code,
                "params": params,
                "message": message,
            }
        )
        self._publish_safe(client, topic, payload, retain=False)

    def publish_state(self, counts: dict[str, int]) -> None:
        """Publish live state counts to the three retained state topics.

        Parameters
        ----------
        counts:
            Dict with keys ``low_stock_count``, ``expiring_count``,
            ``expired_count`` (all integers).

        Topics
        ------
        ``{prefix}/state/low_stock_count`` (retained=True)
        ``{prefix}/state/expiring_count``  (retained=True)
        ``{prefix}/state/expired_count``   (retained=True)
        """
        client, prefix = self._get_client_and_prefix()
        if client is None:
            return

        for key in ("low_stock_count", "expiring_count", "expired_count"):
            value = counts.get(key, 0)
            topic = f"{prefix}/state/{key}"
            self._publish_safe(client, topic, str(value), retain=True)

    def publish_discovery(self) -> None:
        """Publish Home Assistant MQTT discovery configs (if ``discovery_enabled``).

        Gated by ``channels.mqtt.discovery_enabled``.  Called on connect and
        optionally on configuration change.  No-op when not connected or when
        discovery is disabled.
        """
        with self._lock:
            client = self._client
            config = self._config

        if client is None or config is None:
            return
        if not config.discovery_enabled:
            return
        self._publish_discovery_unsafe(client, config.topic_prefix)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client_and_prefix(self) -> tuple[Any, str]:
        """Return (client, prefix) if connected, else (None, '')."""
        with self._lock:
            if not self._connected or self._client is None:
                return None, ""
            prefix = self._config.topic_prefix if self._config else "omniventory"
            return self._client, prefix

    def _publish_safe(self, client: Any, topic: str, payload: str, *, retain: bool) -> None:
        """Publish with best-effort error handling."""
        try:
            client.publish(topic, payload, retain=retain)
            logger.debug("MqttBridge: published to %s (retain=%s).", topic, retain)
        except Exception:
            logger.exception("MqttBridge: failed to publish to %s — ignored.", topic)

    def _publish_discovery_unsafe(self, client: Any, prefix: str) -> None:
        """Publish all HA discovery configs (caller holds no lock)."""
        for metric, name in _STATE_METRICS:
            state_topic = f"{prefix}/state/{metric}"
            discovery_topic = f"homeassistant/sensor/omniventory_{metric}/config"
            payload = json.dumps(_discovery_payload(metric, name, state_topic))
            self._publish_safe(client, discovery_topic, payload, retain=True)
        logger.info("MqttBridge: HA discovery configs published.")


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_bridge: MqttBridge = MqttBridge()
_bridge_lock = threading.Lock()


def get_mqtt_bridge() -> MqttBridge:
    """Return the process-level ``MqttBridge`` singleton.

    Both the FastAPI lifespan (start/stop) and any dispatch site (scheduler
    job, route handler) should call this to access the shared bridge instance.
    """
    return _bridge


def _reset_bridge_for_testing() -> None:
    """Replace the singleton with a fresh instance — **test use only**.

    Tests that need a clean bridge state call this before their fixture
    to avoid cross-test state leakage.
    """
    global _bridge  # noqa: PLW0603
    _bridge = MqttBridge()
