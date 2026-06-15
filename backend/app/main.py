"""Application factory for Omniventory.

``create_app()`` is the sole public entry point.  It builds and returns the
FastAPI application instance.  No app object or Settings are instantiated at
module-import time — all side-effectful work happens inside the factory
function, which is called explicitly (e.g. by the ASGI server or by tests).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI


def _bootstrap_admin() -> None:
    """Idempotently create the admin user from ``admin_bootstrap_*`` settings.

    Called during the FastAPI lifespan startup (NOT at import time).

    Rules:
    - If ``admin_bootstrap_email`` or ``admin_bootstrap_password`` is unset
      (``None`` / empty), skip silently.
    - If the ``users`` table does not yet exist (schema not migrated), skip
      silently — same best-effort policy as ``_purge_expired_sessions``.
    - If a user with that email already exists, skip (idempotent).
    - Otherwise, create the admin user with the hashed password.

    No exception is raised on "already exists" — re-running the app with the
    same bootstrap env is a no-op.
    """
    from sqlalchemy import inspect as sa_inspect

    from app.auth.passwords import hash_password
    from app.config import get_settings
    from app.db.base import get_engine, get_session_factory
    from app.repositories.user import UserRepository

    settings = get_settings()

    if not settings.admin_bootstrap_email or not settings.admin_bootstrap_password:
        return  # Bootstrap env not configured — skip.

    if not sa_inspect(get_engine()).has_table("users"):
        return  # Schema not yet migrated — skip silently.

    factory = get_session_factory()
    db = factory()
    try:
        repo = UserRepository(db)
        existing = repo.get_by_email(settings.admin_bootstrap_email)
        if existing is not None:
            return  # Already bootstrapped — no-op.

        repo.create(
            email=settings.admin_bootstrap_email,
            password_hash=hash_password(settings.admin_bootstrap_password),
            role="admin",
            is_active=True,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _purge_expired_sessions() -> None:
    """Delete expired session rows on application startup.

    This is the actual cleanup mechanism for expired sessions.  ``verify``
    is a pure read (it rejects but does not delete expired rows), so this
    startup sweep keeps the table tidy without relying on per-request
    side-effects that could be silently rolled back by error handlers.

    The sweep is best-effort: if the ``sessions`` table does not yet exist
    (e.g. on a fresh DB before ``alembic upgrade head`` has been run) the
    function skips silently rather than crashing the app.  The table-existence
    check uses ``sqlalchemy.inspect`` so no raw SQL hits the DB when the
    schema isn't present.

    For a long-running deployment a proper periodic job (cron / APScheduler)
    should be added later; the startup sweep is sufficient for M0's single-
    user, self-hosted use-case.
    """
    from sqlalchemy import inspect as sa_inspect

    from app.auth.sessions import purge_expired
    from app.db.base import get_engine, get_session_factory

    engine = get_engine()
    if not sa_inspect(engine).has_table("sessions"):
        return  # Schema not yet migrated — skip silently.

    factory = get_session_factory()
    db = factory()
    try:
        count = purge_expired(db)
        db.commit()
        if count:
            import logging

            logging.getLogger(__name__).info("Purged %d expired session(s) on startup.", count)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:  # noqa: ARG001
    """FastAPI lifespan: run admin bootstrap and expired-session purge on startup."""
    _purge_expired_sessions()
    _bootstrap_admin()
    yield


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application.

    Deliberately avoids import-time side effects:
    - ``get_settings()`` is called *inside* this function, not at module level.
    - No module-level ``app = FastAPI()`` — callers invoke ``create_app()``.

    This makes the factory safe to import in tests and scripts without
    triggering env reads or network I/O.
    """
    # Import here (inside the factory) so that Settings are not read at module
    # import time.  Tests can call ``get_settings.cache_clear()`` before
    # ``create_app()`` to inject test-specific env vars.
    from app.config import get_settings

    settings = get_settings()

    app = FastAPI(
        title="Omniventory",
        description="Self-hosted three-in-one inventory system.",
        version="0.1.0",
        lifespan=_lifespan,
        # Disable the default /docs and /redoc under root; they will be
        # accessible under the api_prefix once routers are mounted.
        docs_url=f"{settings.api_prefix}/docs",
        redoc_url=f"{settings.api_prefix}/redoc",
        openapi_url=f"{settings.api_prefix}/openapi.json",
    )

    # ------------------------------------------------------------------ #
    # Root API router — all routes live under settings.api_prefix          #
    # ------------------------------------------------------------------ #
    from app.api.routes import auth, health

    root_router = APIRouter()
    root_router.include_router(health.router)
    root_router.include_router(auth.router)

    app.include_router(root_router, prefix=settings.api_prefix)

    return app
