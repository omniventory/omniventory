"""Alembic migration environment.

This module is executed by Alembic for every migration command
(``upgrade``, ``downgrade``, ``revision``, etc.).

Key design choices
------------------
- ``database_url`` is read from ``app.config.Settings`` — the same source as
  the running application.  No connection strings are hardcoded in
  ``alembic.ini`` or here.
- ``target_metadata`` is set to ``Base.metadata`` after importing all models,
  so Alembic can auto-detect schema drift.
- Both offline (SQL script) and online (live connection) modes are supported.
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# ---------------------------------------------------------------------------
# Ensure the backend root (parent of this file's parent) is on sys.path so
# that ``import app`` works regardless of which directory Alembic is invoked
# from.  ``alembic/env.py`` lives at ``backend/alembic/env.py``, so:
#   Path(__file__).parent        → backend/alembic/
#   Path(__file__).parent.parent → backend/          ← the package root
# ---------------------------------------------------------------------------
_backend_root = Path(__file__).parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

# ---------------------------------------------------------------------------
# Alembic Config object — gives access to .ini values
# ---------------------------------------------------------------------------
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Inject the database URL from application settings
# ---------------------------------------------------------------------------
# Import here (not at module top-level) to avoid side-effects at import time.
from app.config import get_settings  # noqa: E402

_settings = get_settings()
config.set_main_option("sqlalchemy.url", _settings.database_url)

# ---------------------------------------------------------------------------
# Target metadata: import all models so Alembic sees every table
# ---------------------------------------------------------------------------
import app.models  # noqa: E402, F401 — registers all models with Base.metadata
from app.db.base import Base  # noqa: E402

target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Offline migration (generates SQL without a live DB connection)
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine; by
    skipping the Engine creation we don't even need a DBAPI to be available.
    Calls to ``context.execute()`` here emit the given string to the output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # Required for SQLite ALTER TABLE support.
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migration (uses a live DB connection)
# ---------------------------------------------------------------------------


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine and associate a connection
    with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # NullPool: no connection reuse — good for migrations.
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # Required for SQLite ALTER TABLE support.
        )

        with context.begin_transaction():
            context.run_migrations()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
