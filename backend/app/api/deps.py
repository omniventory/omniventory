"""FastAPI dependencies for the auth layer.

``get_current_user``
    Reads the session cookie, validates the server-side session, and returns
    the authenticated ``User``.  Raises ``HTTP 401`` if the cookie is absent,
    the session is missing / expired, or the user account is inactive.

Naming convention
-----------------
Route handlers import and use ``get_current_user`` directly as a ``Depends``
argument — the name clearly signals "this resolves the current user":

    @router.get("/auth/me")
    def me(user: User = Depends(get_current_user)) -> ...:
        ...

Only authenticated routes depend on ``get_current_user``.  Public endpoints
(e.g. ``/health``, ``/auth/login``) must NOT use this dependency.
"""

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.auth import sessions as session_auth
from app.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.db.session import get_db
from app.models.user import User
from app.repositories.user import UserRepository


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Resolve and return the currently authenticated user.

    Reads the session cookie whose name is configured in ``Settings`` (default
    ``omniventory_session``), validates the server-side session, and returns
    the owning ``User`` ORM object.

    Raises ``HTTP 401`` in these cases:
    - Cookie is absent.
    - Session id is not found in the DB.
    - Session has expired (``expires_at`` in the past).
    - The associated user account is inactive (``is_active=False``).

    Note on ``Secure`` cookie + local dev
    --------------------------------------
    The ``Secure`` flag is set by the login route only when
    ``settings.environment == "production"`` (see ``app/api/routes/auth.py``).
    This means in ``development``/``test`` the cookie is sent over plain HTTP
    so TestClient and ``localhost`` work without TLS.  The ``HttpOnly`` and
    ``SameSite=Lax`` flags are **always** set regardless of environment.
    In production the ``Secure`` flag ensures the cookie is only transmitted
    over HTTPS.  Tests that exercise the ``me`` endpoint set the cookie
    manually on the TestClient (or use a non-production environment) to avoid
    the Secure restriction.
    """
    settings = get_settings()
    session_id: str | None = request.cookies.get(settings.session_cookie_name)

    if not session_id:
        raise AppError(
            ErrorCode.NOT_AUTHENTICATED,
            status_code=401,
            message="Not authenticated",
        )

    session = session_auth.verify(db, session_id)
    if session is None:
        raise AppError(
            ErrorCode.SESSION_INVALID,
            status_code=401,
            message="Session expired or invalid",
        )

    repo = UserRepository(db)
    user = repo.get_by_id(session.user_id)
    if user is None or not user.is_active:
        raise AppError(
            ErrorCode.ACCOUNT_INACTIVE,
            status_code=401,
            message="User not found or inactive",
        )

    return user
