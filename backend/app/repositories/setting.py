"""Repository for user-facing key/value configuration (Setting table, M4 §4.1).

All DB access to ``settings`` goes through this class.  Callers must not
issue raw queries against the table directly.

Public methods
--------------
``get(key)``        Fetch a value by key; returns ``str | None``.
``set(key, value)`` Insert or update a key/value pair (upsert).
``get_all()``       Return a mapping of all stored key/value pairs.
"""

from sqlalchemy.orm import Session

from app.models.setting import Setting


class SettingsRepository:
    """Data-access object for user-editable Setting key/value entries."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, key: str) -> str | None:
        """Return the stored value for ``key``, or ``None`` if absent."""
        row = self._db.get(Setting, key)
        return row.value if row is not None else None

    def set(self, key: str, value: str) -> None:
        """Insert or update the ``key``/``value`` pair (portable upsert).

        Uses ``Session.merge()`` which performs an identity-map upsert: if a
        row with this primary key already exists it is updated; otherwise a
        new row is inserted.  This is dialect-agnostic — works with SQLite
        today and Postgres later without change.  The caller must commit.
        """
        self._db.merge(Setting(key=key, value=value))

    def get_all(self) -> dict[str, str]:
        """Return all stored key/value pairs as a plain dict."""
        rows = self._db.query(Setting).all()
        return {row.key: row.value for row in rows}
