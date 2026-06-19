"""SQLAlchemy model for user-facing key/value configuration (M4 §3.1).

``Setting`` is the ORM representation of the ``settings`` table, which
stores user-editable configuration such as reminder lead times and channel
settings.

Design notes
------------
- ``key``        Dot-namespaced string PK (e.g. ``reminders.best_before_lead_days``,
                 ``channels.mqtt.host``).  Max 128 characters.
- ``value``      Stored as plain text; JSON-encoded for structured values
                 (e.g. the repeat-days list).  The ``SettingsService`` handles
                 (de)serialisation.
- ``updated_at`` Set by the DB on INSERT (``server_default=now()``); refreshed by
                 SQLAlchemy on every UPDATE via ``onupdate=func.now()`` — this
                 satisfies the M4 §3.1 requirement "refreshed on upsert".

Kept SEPARATE from:
- ``AppConfig``         (server-managed secrets — never user-editable)
- ``Household.settings`` (a legacy JSON blob — left untouched by M4)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Setting(Base):
    """Key/value store for user-editable application configuration.

    Columns
    -------
    key         Dot-namespaced identifier; primary key.
    value       Stored value (plain text, JSON-encoded when structured).
    updated_at  Set on INSERT by the DB; refreshed on every UPDATE by SQLAlchemy
                (``onupdate=func.now()``), as required by M4 §3.1.
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"Setting(key={self.key!r})"
