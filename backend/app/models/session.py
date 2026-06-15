"""SQLAlchemy model for server-side auth sessions.

Each row represents one active login.  The session ``id`` is an opaque
random token (``secrets.token_urlsafe``) that travels in the ``HttpOnly``
cookie.  No user data is embedded in the cookie value.

Revocation = deleting the row.  Expiry is checked in the application layer
(``app.auth.sessions.verify``) by comparing ``expires_at`` to ``now(UTC)``.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Session(Base):
    """A server-side session row.

    Columns
    -------
    id            Opaque random token (``secrets.token_urlsafe(32)``); PK.
    user_id       FK → users.id; cascade-deleted when the user is deleted.
    created_at    When the session was created (UTC).
    expires_at    Hard expiry; ``verify()`` rejects sessions past this time.
    last_seen_at  Initialised at ``create()``; reserved hook for M6
                  sliding-window expiry — NOT updated by ``verify()`` in M0.
    """

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationship back to the owning user.
    user: Mapped["User"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "User",
        back_populates="sessions",
    )

    def __repr__(self) -> str:
        # Mask the session id: it is a bearer credential and must not leak
        # into logs or tracebacks.  Show only the first 6 characters as a
        # debug hint, followed by "…".
        masked = f"{self.id[:6]}…" if self.id and len(self.id) > 6 else "***"
        return f"Session(id={masked!r}, user_id={self.user_id!r}, expires_at={self.expires_at!r})"
