"""Shared pytest configuration and helpers for the test suite.

This module provides:
- ``drop_all_sqlite`` — a helper that turns off SQLite FK enforcement before
  calling ``Base.metadata.drop_all()``.  With ``PRAGMA foreign_keys=ON`` now
  active in production (Fix 2), the circular FK between ``locations`` and
  ``stock_instances`` causes a teardown ``IntegrityError`` when SQLAlchemy
  cannot determine a safe DROP order.  Disabling FK enforcement during cleanup
  is safe because the tables are being destroyed, not modified.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase


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
