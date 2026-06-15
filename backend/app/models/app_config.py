"""SQLAlchemy model for application-level key/value configuration.

``AppConfig`` is a dedicated table for server-managed settings that must
survive container restarts (e.g. the auto-generated ``secret_key``).

Design notes
------------
- ``key``   String PK — use short, dot-namespaced identifiers like
            ``'secret_key'``.  No collision risk with user/domain config.
- ``value`` Stored as plain text.  Callers are responsible for any
            serialisation / deserialisation they need.
- Kept SEPARATE from ``Household.settings`` (which is user-visible config)
  so server-managed secrets never leak into the user-facing settings API.
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppConfig(Base):
    """Key/value store for server-managed application configuration.

    Columns
    -------
    key    Short identifier string; primary key.
    value  Stored value (plain text).
    """

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(128), primary_key=True, nullable=False)
    value: Mapped[str] = mapped_column(String(4096), nullable=False)

    def __repr__(self) -> str:
        return f"AppConfig(key={self.key!r})"
