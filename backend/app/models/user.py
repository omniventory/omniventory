"""SQLAlchemy model for User accounts.

M0 bootstraps exactly one admin user.  Multi-user (invitations, roles beyond
"is active admin") is deferred to M6.

Design notes
------------
- ``password_hash`` stores the argon2 hash via ``app.auth.passwords``.
  Plaintext passwords are never stored.
- ``role`` is a freeform string now (e.g. ``"admin"``); a proper enum / role
  table comes in M6.
- ``is_active`` lets an admin deactivate an account without deleting it.
- ``created_at`` is filled by the DB server default.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    """A user account in the household.

    Columns
    -------
    id            Auto-increment surrogate PK.
    email         Unique login identifier; lower-cased on write.
    password_hash Argon2 hash via ``app.auth.passwords.hash_password``.
    role          Role label (``"admin"`` in M0); expanded in M6.
    is_active     False → account is disabled; login is rejected.
    created_at    Row-creation timestamp (UTC, set by DB on insert).
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(1024), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Back-reference to sessions (lazy-loaded on demand).
    sessions: Mapped[list["Session"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Session",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, email={self.email!r}, role={self.role!r})"
