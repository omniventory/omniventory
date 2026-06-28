"""Shared pytest configuration and helpers for the test suite.

This module provides:
- ``drop_all_sqlite`` — a helper that turns off SQLite FK enforcement before
  calling ``Base.metadata.drop_all()``.  With ``PRAGMA foreign_keys=ON`` now
  active in production (Fix 2), the circular FK between ``locations`` and
  ``stock_instances`` causes a teardown ``IntegrityError`` when SQLAlchemy
  cannot determine a safe DROP order.  Disabling FK enforcement during cleanup
  is safe because the tables are being destroyed, not modified.
- ``_reset_rate_limiter`` (autouse fixture) — resets the in-memory rate-limiter
  singleton before each test so that failure counts accumulated in previous
  tests never lock out later test clients (M6 Step 7).
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> Generator[None]:
    """Reset the in-memory rate limiter before (and after) each test.

    The ``RateLimiter`` is a process-level singleton (``app.core.rate_limit``).
    Many tests perform login attempts from the same TestClient IP (127.0.0.1),
    so failures from one test would accumulate and lock out subsequent tests
    without this reset.

    This fixture runs for *every* test in the suite (autouse=True).
    """
    from app.core.rate_limit import get_rate_limiter

    get_rate_limiter().reset()
    yield
    get_rate_limiter().reset()


def drop_all_sqlite(base: type[DeclarativeBase], engine: Engine) -> None:
    """Drop all tables, disabling SQLite FK enforcement first.

    Needed because the circular FK between ``locations`` ↔ ``stock_instances``
    prevents SQLAlchemy from ordering the DROPs correctly when FK enforcement
    is active.  This is only a test-teardown concern; production never needs
    to bulk-drop all tables.
    """
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.commit()
    base.metadata.drop_all(engine)
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.commit()
