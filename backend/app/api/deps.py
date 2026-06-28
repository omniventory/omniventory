"""FastAPI dependencies for the auth layer.

``get_current_user``
    Reads the session cookie, validates the server-side session, and returns
    the authenticated ``User``.  Raises ``HTTP 401`` if the cookie is absent,
    the session is missing / expired, or the user account is inactive.

``require_permission(perm)``
    Factory that returns a FastAPI dependency for the given ``Permission``
    constant.  The dependency resolves the current user (via
    ``get_current_user``) and raises ``HTTP 403 auth.forbidden`` when the
    user's role lacks the required permission.  On success it returns the
    ``User`` so callers can reuse it without an extra dependency.

    Thin shortcuts for the common cases::

        require_edit            = require_permission(Permission.EDIT)
        require_manage_users    = require_permission(Permission.MANAGE_USERS)
        require_manage_settings = require_permission(Permission.MANAGE_SETTINGS)
        require_view_audit      = require_permission(Permission.VIEW_AUDIT)

    Usage in a route::

        @router.post("/locations")
        def create_location(
            body: LocationCreate,
            _ctx: RequestContext = Depends(get_authenticated_context),
            _: User = Depends(require_edit),
        ) -> LocationResponse:
            ...

``auth_rate_limit(scope)``
    Factory that returns a FastAPI dependency for the given rate-limit scope.
    The dependency calls ``limiter.check(scope, key)`` *before* the handler.
    Returns a ``RateLimitHandle`` whose ``.register_failure()`` and ``.clear()``
    the handler calls on the failure / success branch.

    Key computation:
    - Most scopes (``"login"``, ``"setup"``, ``"invite_accept"``,
      ``"reset_accept"``): key = ``request.client.host``.
    - ``"change_password"``: key = ``"<client_ip>:<user_id>"`` (also resolves
      the current user so the caller gets their ``user.id``).

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

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.auth import sessions as session_auth
from app.auth.permissions import Permission, has_permission
from app.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.rate_limit import get_rate_limiter
from app.db.session import get_db
from app.models.user import User
from app.repositories.user import UserRepository

# ---------------------------------------------------------------------------
# Rate-limit handle (returned by the auth_rate_limit dependency)
# ---------------------------------------------------------------------------


@dataclass
class RateLimitHandle:
    """Bound accessor for a single ``(scope, key)`` slot in the rate limiter.

    Returned by ``auth_rate_limit(scope)`` dependencies so route handlers can
    record failures or clear the counter without importing the limiter directly.

    Usage in a route::

        rl_handle: RateLimitHandle = Depends(auth_rate_limit("login"))
        ...
        if bad_creds:
            rl_handle.register_failure()
            raise AppError(...)
        rl_handle.clear()  # success
    """

    _scope: str
    _key: str

    def register_failure(self) -> None:
        """Record a failed attempt.  Call before raising the error response."""
        get_rate_limiter().register_failure(self._scope, self._key)

    def clear(self) -> None:
        """Clear all state for this key.  Call on a successful attempt."""
        get_rate_limiter().clear(self._scope, self._key)


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


# ---------------------------------------------------------------------------
# Permission-gating dependency factory (M6 Step 1)
# ---------------------------------------------------------------------------


def require_permission(perm: str) -> Callable[..., User]:
    """Return a FastAPI dependency that enforces the given permission.

    The returned callable resolves the current user (via ``get_current_user``)
    and raises ``HTTP 403 auth.forbidden`` when the user's role does not grant
    *perm*.  On success it returns the ``User`` so callers can reuse it.

    Parameters
    ----------
    perm:
        A ``Permission.*`` constant (e.g. ``Permission.EDIT``).

    Usage
    -----
    ::

        @router.post("/locations")
        def create_location(
            body: LocationCreate,
            _ctx: RequestContext = Depends(get_authenticated_context),
            _: User = Depends(require_permission(Permission.EDIT)),
        ) -> LocationResponse:
            ...

    Or via the named shortcuts::

        _: User = Depends(require_edit)
    """

    def _check(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user.role, perm):
            raise AppError(
                ErrorCode.FORBIDDEN,
                status_code=403,
            )
        return user

    # Give the inner function a meaningful name so FastAPI's dependency graph
    # and tracebacks are readable.
    _check.__name__ = f"require_permission_{perm}"
    return _check


# Thin named shortcuts — usable as ``Depends(require_edit)`` etc.
require_edit: Callable[..., User] = require_permission(Permission.EDIT)
require_manage_users: Callable[..., User] = require_permission(Permission.MANAGE_USERS)
require_manage_settings: Callable[..., User] = require_permission(Permission.MANAGE_SETTINGS)
require_view_audit: Callable[..., User] = require_permission(Permission.VIEW_AUDIT)


# ---------------------------------------------------------------------------
# Rate-limit dependency factory (M6 Step 7)
# ---------------------------------------------------------------------------


def auth_rate_limit(scope: str) -> Callable[..., RateLimitHandle]:
    """Return a FastAPI dependency that enforces rate limiting for *scope*.

    The returned dependency:
    1. Computes the key (``client_ip`` for most scopes; ``<ip>:<user_id>``
       for ``"change_password"``).
    2. Calls ``limiter.check(scope, key)`` — raises 429 ``auth.rate_limited``
       if currently locked out.
    3. Returns a ``RateLimitHandle`` so the route can call
       ``.register_failure()`` on bad-cred / bad-token paths and ``.clear()``
       on success.

    Parameters
    ----------
    scope:
        Logical namespace for the limit counter, e.g. ``"login"``,
        ``"setup"``, ``"invite_accept"``, ``"reset_accept"``,
        ``"change_password"``.

    Usage::

        @router.post("/auth/login")
        def login(..., rl: RateLimitHandle = Depends(auth_rate_limit("login"))):
            ...
            if bad_creds:
                rl.register_failure()
                raise AppError(INVALID_CREDENTIALS, 401)
            rl.clear()
            ...
    """
    if scope == "change_password":
        # For change-password the key includes the user_id so each user gets
        # their own independent counter (even when behind a shared NAT).
        def _dep_with_user(
            request: Request,
            user: User = Depends(get_current_user),
        ) -> RateLimitHandle:
            client_ip = request.client.host if request.client else "unknown"
            key = f"{client_ip}:{user.id}"
            get_rate_limiter().check(scope, key)
            return RateLimitHandle(_scope=scope, _key=key)

        _dep_with_user.__name__ = f"auth_rate_limit_{scope}"
        return _dep_with_user
    else:
        # All other scopes key on client IP only.
        def _dep_ip_only(request: Request) -> RateLimitHandle:
            client_ip = request.client.host if request.client else "unknown"
            get_rate_limiter().check(scope, client_ip)
            return RateLimitHandle(_scope=scope, _key=client_ip)

        _dep_ip_only.__name__ = f"auth_rate_limit_{scope}"
        return _dep_ip_only
