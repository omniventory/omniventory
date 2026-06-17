"""Authentication endpoints.

POST {prefix}/auth/login    Verify credentials → create session → set cookie.
POST {prefix}/auth/logout   Revoke server-side session + clear cookie.
GET  {prefix}/auth/me       Return current user (401 if no/invalid session).

Cookie policy (``HttpOnly`` + ``SameSite=Lax`` always; ``Secure`` in production)
----------------------------------------------------------------------------------
The ``Secure`` flag prevents the browser from sending the cookie over plain HTTP.
This is correct and required in production (HTTPS only).  However, it breaks
two scenarios in development/testing:

  1. ``TestClient`` drives requests over ``http://testserver`` — not HTTPS.
  2. ``localhost`` development without TLS.

Resolution: the ``Secure`` flag is driven by ``settings.environment``.
- ``"production"``                     → ``Secure=True``   (HTTPS required).
- ``"development"`` / ``"test"`` / *   → ``Secure=False``  (plain HTTP OK).

``HttpOnly`` and ``SameSite=Lax`` are **always** set regardless of environment,
so XSS cannot steal the token and CSRF is mitigated in all environments.

Tests that exercise ``/auth/me`` (the authenticated route) use the non-
production environment (``ENVIRONMENT=test``) so the cookie is sent back by
the TestClient's HTTP transport without needing TLS.  The production
``Secure`` requirement is verified by a separate unit test that checks the
flag logic directly (without needing HTTPS infrastructure).
"""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.auth import sessions as session_auth
from app.auth.passwords import dummy_verify, hash_password, verify_password
from app.config import get_settings
from app.core.errors import AppError, ErrorCode, ErrorResponse
from app.db.session import get_db
from app.models.app_config import AppConfig
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    MessageResponse,
    SetupRequest,
    SetupStatusResponse,
    UserResponse,
)

_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

router = APIRouter(prefix="/auth", tags=["auth"], responses=_ERROR_RESPONSES)


def _set_session_cookie(response: Response, session_id: str) -> None:
    """Set the session cookie on ``response`` with the correct flags.

    ``HttpOnly``    Always set — JS cannot read the cookie value.
    ``SameSite``    Always ``Lax`` — safe default that allows top-level nav
                    but blocks cross-site sub-resource requests.
    ``Secure``      Set only in ``production`` — prevents sending over HTTP.
                    In dev/test this is relaxed so plain-HTTP flows work.
    """
    settings = get_settings()
    is_production = settings.environment == "production"
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=is_production,
        # No ``max_age`` — the session expiry is enforced server-side.
        # The browser will treat it as a session cookie (cleared on close),
        # but the server-side expiry is the authoritative gate.
    )


def _clear_session_cookie(response: Response) -> None:
    """Clear the session cookie from the browser."""
    settings = get_settings()
    is_production = settings.environment == "production"
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        samesite="lax",
        secure=is_production,
    )


@router.post("/login", response_model=UserResponse)
def login(
    body: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> UserResponse:
    """Authenticate with email + password and return a session cookie.

    On success: creates a server-side session row and sets the ``HttpOnly``
    session cookie.  Returns the public user object.

    On failure: returns 401 (email not found or wrong password).  The same
    error is returned for both cases to prevent user-enumeration attacks.
    """
    repo = UserRepository(db)
    user = repo.get_by_email(body.email)

    if user is None:
        # Consume time comparable to a real hash verification to prevent
        # user-enumeration via response timing.
        dummy_verify(body.password)
        raise AppError(
            ErrorCode.INVALID_CREDENTIALS,
            status_code=401,
            message="Invalid credentials",
        )

    if not verify_password(body.password, user.password_hash):
        raise AppError(
            ErrorCode.INVALID_CREDENTIALS,
            status_code=401,
            message="Invalid credentials",
        )

    if not user.is_active:
        raise AppError(
            ErrorCode.ACCOUNT_DISABLED,
            status_code=401,
            message="Account is disabled",
        )

    session = session_auth.create(db, user.id)
    _set_session_cookie(response, session.id)

    return UserResponse.model_validate(user)


@router.post("/logout", response_model=MessageResponse)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Revoke the current session and clear the cookie.

    Idempotent: if the cookie is absent or the session is already gone, the
    endpoint still returns 200 and clears the cookie.
    """
    settings = get_settings()
    session_id: str | None = request.cookies.get(settings.session_cookie_name)
    if session_id:
        session_auth.revoke(db, session_id)
    _clear_session_cookie(response)
    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user)) -> MeResponse:
    """Return the currently authenticated user.

    Requires a valid session cookie.  Returns 401 if absent / expired.
    """
    return MeResponse(user=UserResponse.model_validate(user))


# ---------------------------------------------------------------------------
# First-run onboarding endpoints (unauthenticated)
# ---------------------------------------------------------------------------


@router.get("/setup-status", response_model=SetupStatusResponse)
def setup_status(db: Session = Depends(get_db)) -> SetupStatusResponse:
    """Return whether first-run setup is still required.

    ``setup_required: true``  — no users exist; the setup page must be shown.
    ``setup_required: false`` — at least one user exists; show the login page.

    Unauthenticated — the frontend calls this on every load to decide which
    page to show before the user has any session cookie.
    """
    repo = UserRepository(db)
    return SetupStatusResponse(setup_required=repo.count() == 0)


_ONBOARDING_SENTINEL_KEY = "onboarding_completed"


@router.post("/setup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def setup(
    body: SetupRequest,
    db: Session = Depends(get_db),
) -> UserResponse:
    """Create the first admin user (first-run onboarding).

    Self-closing and concurrency-safe: the admin user and a sentinel row
    (``app_config.key = 'onboarding_completed'``) are created in a **single
    transaction**.  Because ``app_config.key`` is the primary key, a second
    concurrent request that also passes the fast-path pre-check will hit a
    primary-key ``IntegrityError`` when it tries to insert the same sentinel,
    causing its transaction to roll back → 409.

    This works even when two concurrent requests each read ``count == 0`` with
    *different* emails (which would bypass the email-unique constraint alone):
    only one can win the sentinel insert; the loser always gets 409.

    Fast-path pre-check (sentinel exists or any user exists → 409) is kept for
    the common case, but the correctness guarantee comes from the unique-key
    sentinel insert, not from the pre-check.

    On success returns the created user (HTTP 201).  Does NOT auto-login —
    the frontend transitions to the normal login screen after setup.
    """
    repo = UserRepository(db)

    # Fast-path: sentinel already written or user already exists → skip the
    # expensive password hash and return immediately.
    sentinel_exists = db.get(AppConfig, _ONBOARDING_SENTINEL_KEY) is not None
    if sentinel_exists or repo.count() > 0:
        raise AppError(
            ErrorCode.SETUP_ALREADY_COMPLETE,
            status_code=409,
            message="Setup already complete: an admin user already exists.",
        )

    # Insert both the user and the sentinel atomically.  If another concurrent
    # request races to the same point, one of them will raise IntegrityError on
    # the sentinel's primary-key uniqueness → translated to 409 below.
    user = repo.create(
        email=body.email,
        password_hash=hash_password(body.password),
        role="admin",
        is_active=True,
    )
    db.flush()  # Assign user.id before inserting the sentinel.
    sentinel = AppConfig(key=_ONBOARDING_SENTINEL_KEY, value="true")
    db.add(sentinel)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(
            ErrorCode.SETUP_ALREADY_COMPLETE,
            status_code=409,
            message="Setup already complete: an admin user already exists.",
        ) from None

    db.refresh(user)
    return UserResponse.model_validate(user)
