"""SQLAlchemy 2.0 typed declarative base, engine, and session factory.

All models import ``Base`` from here to share a single metadata object, which
Alembic's ``env.py`` then targets for migration auto-detection.

Engine and session factory are built lazily (inside ``get_engine()`` /
``get_session_factory()``) rather than at module import time, so tests can
override ``database_url`` via environment before the engine is constructed.
"""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# ---------------------------------------------------------------------------
# Single typed declarative base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Project-wide SQLAlchemy declarative base.

    Every model inherits from this to participate in the shared metadata and
    to use the SQLAlchemy 2.0 ``Mapped[...]`` typed column style.
    """


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@lru_cache
def get_engine() -> Engine:
    """Build and return the SQLAlchemy engine (cached per process).

    Reads ``database_url`` from the application settings so the same config
    path used everywhere else drives DB connectivity.  For SQLite we apply
    sane connect args:
    - ``check_same_thread=False`` — required because FastAPI/ASGI may call the
      same connection from multiple greenlets/threads.
    - ``timeout=30`` — wait up to 30 s for a lock rather than failing instantly
      under brief write contention.
    """
    from app.config import get_settings

    settings = get_settings()
    url = settings.database_url

    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False, "timeout": 30}

    return create_engine(
        url,
        connect_args=connect_args,
        # Echo SQL only in development for debugging.
        echo=settings.environment == "development",
    )


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    # Bind lazily so that tests can call get_engine() after setting up their
    # temp DB.  The factory is re-bound by get_session_factory() below.
)


def get_session_factory() -> sessionmaker:  # type: ignore[type-arg]
    """Return a session factory bound to the current engine.

    Creates a new ``sessionmaker`` bound to the engine returned by
    ``get_engine()``.  This is separate from the module-level ``SessionLocal``
    so that tests can patch the engine without affecting the global object.
    """
    return sessionmaker(
        bind=get_engine(),
        autocommit=False,
        autoflush=False,
    )
