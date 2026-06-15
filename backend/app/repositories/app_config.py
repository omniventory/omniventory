"""Repository for application-level key/value configuration (AppConfig table).

All DB access to ``app_config`` goes through this class.  Callers must not
issue raw queries against the table directly.

Public methods
--------------
``get(key)``        Fetch a value by key; returns ``str | None``.
``set(key, value)`` Insert or update a key/value pair (upsert).
"""

from sqlalchemy.orm import Session

from app.models.app_config import AppConfig


class AppConfigRepository:
    """Data-access object for AppConfig key/value entries."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, key: str) -> str | None:
        """Return the stored value for ``key``, or ``None`` if absent."""
        row = self._db.get(AppConfig, key)
        return row.value if row is not None else None

    def set(self, key: str, value: str) -> None:
        """Insert or update the ``key``/``value`` pair (portable upsert).

        Uses ``Session.merge()`` which performs an identity-map upsert: if a
        row with this primary key already exists it is updated; otherwise a
        new row is inserted.  This is dialect-agnostic — works with SQLite
        today and Postgres later without change.  The caller must commit.
        """
        self._db.merge(AppConfig(key=key, value=value))
