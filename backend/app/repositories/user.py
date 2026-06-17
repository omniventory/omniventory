"""Repository for User accounts.

All DB access to the ``users`` table goes through this class.  Route handlers
and services must not issue raw queries against ``users``; they call
``UserRepository`` methods.

Public methods
--------------
``get_by_id(id)``                       Fetch by PK; returns ``User | None``.
``get_by_email(email)``                 Fetch by (lowercased) email; returns ``User | None``.
``create(email, hash, role, is_active)``  Insert a new user row.
``count()``                             Return total user count (used by bootstrap guard).
``set_preferred_language(user, lang)``  Update the user's preferred_language and flush.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    """Data-access object for User accounts."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_id(self, user_id: int) -> User | None:
        """Return a User by primary key, or None if not found."""
        return self._db.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        """Return a User by email (case-insensitive match), or None."""
        stmt = select(User).where(func.lower(User.email) == email.lower())
        return self._db.execute(stmt).scalar_one_or_none()

    def create(
        self,
        *,
        email: str,
        password_hash: str,
        role: str = "admin",
        is_active: bool = True,
    ) -> User:
        """Insert and return a new User row.

        ``email`` is stored lower-cased for consistent case-insensitive lookup.
        ``password_hash`` must already be hashed via ``app.auth.passwords``.
        The caller must commit (or flush within a ``get_db`` transaction).
        """
        user = User(
            email=email.lower(),
            password_hash=password_hash,
            role=role,
            is_active=is_active,
        )
        self._db.add(user)
        self._db.flush()
        return user

    def count(self) -> int:
        """Return the total number of user rows."""
        result = self._db.execute(select(func.count()).select_from(User))
        value = result.scalar()
        return int(value) if value is not None else 0

    def set_preferred_language(self, user: User, language: str | None) -> User:
        """Update the user's preferred_language and flush.

        Pass ``None`` to explicitly unset the preference (→ NULL in DB),
        which re-enables the client-side resolution chain.
        The caller must commit (or rely on ``get_db``'s auto-commit on
        response).
        """
        user.preferred_language = language
        self._db.flush()
        return user
