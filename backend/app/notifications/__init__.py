"""Notification delivery infrastructure (M4 Phase C).

Packages:
    dispatcher    NotificationDispatcher — iterates enabled channel adapters.
    channels/     Channel adapter implementations (Phase C: email, http, mqtt).

Step 3 ships the dispatcher with an in-app stub and the channel protocol.
External channel adapters (EmailChannel, HttpChannel, MqttChannel) land in
Steps 7–9.
"""
