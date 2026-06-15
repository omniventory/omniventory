"""FastAPI dependency: ``get_db`` unit-of-work session.

Usage in a route::

    @router.get("/example")
    def example(db: Session = Depends(get_db)) -> ...:
        ...

``get_db`` opens a session, yields it to the route handler, then commits on
success or rolls back on any exception, and always closes the session.
"""

from collections.abc import Generator

from sqlalchemy.orm import Session

from app.db.base import get_session_factory


def get_db() -> Generator[Session]:
    """Yield a database session for the duration of a single request.

    Lifecycle:
    1. Open a new session from the factory.
    2. ``yield`` it to the caller (the route / dependency chain).
    3. On success: commit.
    4. On exception: rollback, then re-raise.
    5. Always: close the session so the connection is returned to the pool.
    """
    factory = get_session_factory()
    db: Session = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
