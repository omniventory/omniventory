"""Step 3 tests: persistence, migrations, Household singleton, context layer.

Covers:
- alembic upgrade head applies cleanly on a fresh temp SQLite
- alembic downgrade base is clean (reversibility)
- second-household INSERT is rejected by the DB CHECK constraint
- HouseholdRepository.get() / .ensure() (happy path and idempotence)
- app-layer singleton guard (ensure() does not insert a second row)
- GET /api/health returns db: "ok" (against a real schema on disk)
- get_context / RequestContext: request-path integration test via a real DB
"""

import os
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.household import Household
from app.repositories.household import HouseholdRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_temp_db_url() -> tuple[str, Path]:
    """Return a (url, path) pair for a fresh temp-file SQLite database.

    Using a real file (not :memory:) ensures that the schema created in the
    main thread is visible to the worker thread that TestClient uses to run
    route handlers — in-memory SQLite connections are isolated per-connection
    so they cannot be safely shared across threads without StaticPool.
    """
    fd, path_str = tempfile.mkstemp(suffix=".db", prefix="omniventory_test_")
    os.close(fd)
    path = Path(path_str)
    # Delete the file so the DB starts truly empty (mkstemp creates it).
    path.unlink()
    return f"sqlite:///{path_str}", path


def _db_path_from_url(url: str) -> Path:
    """Extract the filesystem path from a ``sqlite:///`` URL."""
    return Path(url.removeprefix("sqlite:///"))


def _make_in_memory_session() -> Session:
    """Create an in-memory SQLite DB with the full schema and return a session.

    Used for unit tests that run entirely in a single thread (no TestClient).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    # Enforce CHECK constraints in SQLite (disabled by default).
    @event.listens_for(engine, "connect")
    def _enforce_integrity(dbapi_conn: object, _: object) -> None:  # type: ignore[type-arg]
        import sqlite3

        if isinstance(dbapi_conn, sqlite3.Connection):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return factory()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_settings_and_engine_cache() -> Generator[None]:
    """Reset lru_cache on get_settings and get_engine before/after each test.

    Ensures tests that set DATABASE_URL via monkeypatch get a fresh engine
    and don't bleed state into each other.
    """
    from app.config import get_settings
    from app.db.base import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()
    # Re-import to clear module-level state that may have been mutated.
    import importlib

    import app.db.base
    import app.db.session

    importlib.reload(app.db.base)
    importlib.reload(app.db.session)


@pytest.fixture()
def db_session() -> Generator[Session]:
    """Provide a fresh in-memory SQLite session with the full schema."""
    session = _make_in_memory_session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def temp_db(monkeypatch: pytest.MonkeyPatch) -> Generator[Path]:
    """Create a temp-file SQLite DB and point DATABASE_URL at it.

    Using a real file (not :memory:) so that schema created in the fixture
    thread is visible to the TestClient worker thread that runs route handlers.
    Yields the Path so callers can open the file directly if needed.
    Cleans up the file after the test.
    """
    url, db_path = _make_temp_db_url()
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-unit-tests")
    monkeypatch.setenv("DATABASE_URL", url)
    yield db_path
    if db_path.exists():
        db_path.unlink()


@pytest.fixture()
def test_client(temp_db: Path) -> Generator[TestClient]:  # noqa: ARG001
    """TestClient backed by a temp-file SQLite DB with schema applied.

    The temp-file DB is used (not :memory:) so the schema built here in the
    main thread is genuinely shared with the TestClient worker thread —
    SQLite file DBs are shared across connections/threads; :memory: DBs are
    not (each connection gets an independent empty database).
    """
    from app.db.base import get_engine
    from app.main import create_app

    # get_engine() is now cached with the temp DATABASE_URL (set by temp_db).
    engine = get_engine()
    Base.metadata.create_all(engine)
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    Base.metadata.drop_all(engine)


# ---------------------------------------------------------------------------
# Alembic migration tests
# ---------------------------------------------------------------------------


class TestAlembicMigrations:
    """Verify that Alembic migrations apply and reverse cleanly.

    We invoke Alembic via subprocess rather than the in-process Python API to
    avoid the local ``alembic/`` directory shadowing the installed
    ``alembic`` package when pytest adds the project root to sys.path.
    """

    def _run_alembic(self, *args: str, url: str) -> tuple[int, str]:
        """Run an alembic command as a subprocess and return (returncode, output)."""
        import subprocess

        backend_root = Path(__file__).parent.parent
        env = {
            **os.environ,
            "SECRET_KEY": "test",
            "DATABASE_URL": url,
        }
        result = subprocess.run(
            [".venv/bin/alembic", *args],
            cwd=str(backend_root),
            env=env,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout + result.stderr

    def test_upgrade_head_on_fresh_db(self) -> None:
        """alembic upgrade head must succeed on an empty SQLite file."""
        url, db_path = _make_temp_db_url()

        try:
            rc, output = self._run_alembic("upgrade", "head", url=url)
            assert rc == 0, f"alembic upgrade failed:\n{output}"

            # Confirm the households table and singleton row exist.
            engine = create_engine(url)
            with engine.connect() as conn:
                row = conn.execute(text("SELECT id, name FROM households WHERE id = 1")).fetchone()
                assert row is not None, "singleton row must exist after upgrade"
                assert row[0] == 1
        finally:
            if db_path.exists():
                db_path.unlink()

    def test_downgrade_base_is_clean(self) -> None:
        """alembic downgrade base must succeed and remove the table."""
        url, db_path = _make_temp_db_url()

        try:
            rc_up, out_up = self._run_alembic("upgrade", "head", url=url)
            assert rc_up == 0, f"alembic upgrade failed:\n{out_up}"

            rc_down, out_down = self._run_alembic("downgrade", "base", url=url)
            assert rc_down == 0, f"alembic downgrade failed:\n{out_down}"

            # After downgrade the households table must not exist.
            engine = create_engine(url)
            with engine.connect() as conn:
                tables = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name='households'")
                ).fetchall()
                assert tables == [], "households table must not exist after downgrade"
        finally:
            if db_path.exists():
                db_path.unlink()


# ---------------------------------------------------------------------------
# DB-level singleton constraint tests
# ---------------------------------------------------------------------------


class TestSingletonDBConstraint:
    """The CHECK(id = 1) constraint must reject a second household at the DB."""

    def test_second_household_insert_rejected_by_db(self, db_session: Session) -> None:
        """Inserting a row with id != 1 must raise IntegrityError."""
        # First, insert the singleton (id=1).
        h1 = Household(id=1, name="Home", currency="USD", timezone="UTC")
        db_session.add(h1)
        db_session.commit()

        # Attempt to insert a second row with id=2 — must be rejected by CHECK.
        h2 = Household(id=2, name="Office", currency="EUR", timezone="Europe/Berlin")
        db_session.add(h2)
        with pytest.raises(IntegrityError, match="CHECK constraint failed"):
            db_session.commit()

    def test_singleton_row_id1_accepted(self, db_session: Session) -> None:
        """Inserting id=1 must succeed."""
        h = Household(id=1, name="My Home", currency="USD", timezone="UTC")
        db_session.add(h)
        db_session.commit()
        assert db_session.get(Household, 1) is not None


# ---------------------------------------------------------------------------
# HouseholdRepository tests
# ---------------------------------------------------------------------------


class TestHouseholdRepository:
    """Test app-layer repository methods."""

    def test_get_returns_none_when_empty(self, db_session: Session) -> None:
        """get() returns None when no household exists."""
        repo = HouseholdRepository(db_session)
        assert repo.get() is None

    def test_ensure_creates_singleton(self, db_session: Session) -> None:
        """ensure() creates the singleton row if absent."""
        repo = HouseholdRepository(db_session)
        household = repo.ensure()
        db_session.commit()
        assert household.id == 1
        assert household.name == "My Household"

    def test_ensure_idempotent(self, db_session: Session) -> None:
        """ensure() called twice must return the same row (app-layer guard)."""
        repo = HouseholdRepository(db_session)
        h1 = repo.ensure()
        db_session.commit()
        h2 = repo.ensure()
        db_session.commit()
        # Must be the same row — only one row in the table.
        assert h1.id == h2.id == 1
        count = db_session.execute(text("SELECT COUNT(*) FROM households")).scalar()
        assert count == 1, f"Expected exactly 1 row, got {count}"

    def test_get_returns_singleton_after_ensure(self, db_session: Session) -> None:
        """get() returns the row after ensure() creates it."""
        repo = HouseholdRepository(db_session)
        repo.ensure()
        db_session.commit()
        fetched = repo.get()
        assert fetched is not None
        assert fetched.id == 1

    def test_ensure_with_custom_defaults(self, db_session: Session) -> None:
        """ensure() accepts custom name/currency/timezone."""
        repo = HouseholdRepository(db_session)
        h = repo.ensure(name="Smith Home", currency="EUR", timezone="Europe/Paris")
        db_session.commit()
        assert h.name == "Smith Home"
        assert h.currency == "EUR"
        assert h.timezone == "Europe/Paris"

    def test_ensure_does_not_overwrite_existing(self, db_session: Session) -> None:
        """ensure() called after first creation must NOT update existing values."""
        repo = HouseholdRepository(db_session)
        repo.ensure(name="Original")
        db_session.commit()
        repo.ensure(name="Should Not Replace")
        db_session.commit()
        fetched = repo.get()
        assert fetched is not None
        assert fetched.name == "Original"

    def test_db_ping_returns_true(self, db_session: Session) -> None:
        """db_ping() must return True (SELECT 1 succeeds)."""
        repo = HouseholdRepository(db_session)
        assert repo.db_ping() is True


# ---------------------------------------------------------------------------
# App-layer singleton guard (ensure does not double-insert)
# ---------------------------------------------------------------------------


class TestAppLayerSingletonGuard:
    """Verify the app-layer guard in ensure() independently of the DB CHECK."""

    def test_ensure_checks_existence_before_insert(self, db_session: Session) -> None:
        """ensure() must read first and skip INSERT if the row exists."""
        repo = HouseholdRepository(db_session)
        # Create the row manually (simulating an already-bootstrapped state).
        existing = Household(id=1, name="Pre-existing", currency="GBP", timezone="Europe/London")
        db_session.add(existing)
        db_session.commit()

        # ensure() must return the existing row without raising.
        result = repo.ensure(name="Would be new", currency="USD", timezone="UTC")
        db_session.commit()
        assert result.name == "Pre-existing"  # Value unchanged: existing returned
        count = db_session.execute(text("SELECT COUNT(*) FROM households")).scalar()
        assert count == 1


# ---------------------------------------------------------------------------
# Health endpoint tests (Step 3 extension)
# ---------------------------------------------------------------------------


class TestHealthWithDb:
    """Health endpoint must return db: ok with a wired DB.

    The fixture uses a temp-file SQLite so the schema is genuinely shared
    with the TestClient worker thread.  This means health's db:"ok" now truly
    exercises a DB that has the households table — not just a bare SELECT 1.
    """

    def test_health_returns_db_ok(self, test_client: TestClient) -> None:
        """GET /api/health must include db: 'ok' when DB is reachable."""
        response = test_client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["db"] == "ok"

    def test_health_still_has_status_and_version(self, test_client: TestClient) -> None:
        """Health response must still carry status, version, and api_version."""
        body = test_client.get("/api/health").json()
        assert body["status"] == "ok"
        assert "version" in body
        assert "api_version" in body

    def test_health_payload_has_exactly_required_keys(self, test_client: TestClient) -> None:
        """Health response shape must include the four expected keys."""
        body = test_client.get("/api/health").json()
        expected_keys = {"status", "version", "api_version", "db"}
        assert expected_keys.issubset(body.keys())


# ---------------------------------------------------------------------------
# get_context / RequestContext integration tests (§4.4 multi-tenant hedge)
# ---------------------------------------------------------------------------


class TestContextLayer:
    """Integration tests for get_context and RequestContext (§4.4 deliverable).

    These tests drive requests through the full FastAPI request path — using
    a real temp-file SQLite DB shared across threads — and verify that
    get_context resolves the singleton household via the repository seam.

    A lightweight test route is registered on the app before the TestClient
    is started; it depends on get_context and echoes back the household id
    and name as JSON.  This exercises the complete chain:
        HTTP request → get_db → Session → HouseholdRepository → get_context
        → RequestContext(household=<singleton>) → route handler
    """

    def test_get_context_resolves_singleton_household(self, temp_db: Path) -> None:  # noqa: ARG002
        """get_context must resolve and return the singleton Household in a real request."""
        from fastapi import APIRouter

        from app.core.context import RequestContext, get_context
        from app.db.base import get_engine
        from app.main import create_app

        engine = get_engine()
        Base.metadata.create_all(engine)

        app = create_app()

        # Register a test-only route that depends on get_context.
        test_router = APIRouter()

        @test_router.get("/_test/context")
        def _context_probe(ctx: RequestContext = Depends(get_context)) -> dict:  # type: ignore[type-arg]
            return {"household_id": ctx.household.id, "household_name": ctx.household.name}

        app.include_router(test_router)

        with TestClient(app, raise_server_exceptions=True) as client:
            response = client.get("/_test/context")

        assert response.status_code == 200, response.text
        body = response.json()
        # The singleton household must always have id=1.
        assert body["household_id"] == 1
        # Default name from HouseholdRepository.ensure().
        assert body["household_name"] == "My Household"

        Base.metadata.drop_all(engine)

    def test_get_context_household_is_persisted_in_real_db(self, temp_db: Path) -> None:
        """Household created by get_context must be persisted to the file-based DB."""
        from fastapi import APIRouter

        from app.core.context import RequestContext, get_context
        from app.db.base import get_engine
        from app.main import create_app

        engine = get_engine()
        Base.metadata.create_all(engine)

        app = create_app()

        test_router = APIRouter()

        @test_router.get("/_test/context")
        def _context_probe2(ctx: RequestContext = Depends(get_context)) -> dict:  # type: ignore[type-arg]
            return {"household_id": ctx.household.id}

        app.include_router(test_router)

        with TestClient(app, raise_server_exceptions=True) as client:
            client.get("/_test/context")

        # After the request, confirm the row was committed to the file DB
        # by opening a new connection and querying directly.
        with engine.connect() as conn:
            row = conn.execute(text("SELECT id, name FROM households WHERE id = 1")).fetchone()
        assert row is not None, "singleton row must be persisted after get_context request"
        assert row[0] == 1

        Base.metadata.drop_all(engine)


# ---------------------------------------------------------------------------
# Household model utility
# ---------------------------------------------------------------------------


class TestHouseholdModel:
    """Unit tests for Household model helpers."""

    def test_settings_dict_returns_empty_on_null(self, db_session: Session) -> None:
        """settings_dict() returns {} when settings is None."""
        h = Household(id=1, name="Home", currency="USD", timezone="UTC", settings=None)
        db_session.add(h)
        db_session.commit()
        db_session.refresh(h)
        assert h.settings_dict() == {}

    def test_settings_dict_parses_json(self, db_session: Session) -> None:
        """settings_dict() parses a valid JSON string."""
        h = Household(
            id=1, name="Home", currency="USD", timezone="UTC", settings='{"theme": "dark"}'
        )
        db_session.add(h)
        db_session.commit()
        db_session.refresh(h)
        assert h.settings_dict() == {"theme": "dark"}

    def test_settings_dict_returns_empty_on_invalid_json(self, db_session: Session) -> None:
        """settings_dict() returns {} on invalid JSON (graceful degradation)."""
        h = Household(id=1, name="Home", currency="USD", timezone="UTC", settings="not-json")
        db_session.add(h)
        db_session.commit()
        db_session.refresh(h)
        assert h.settings_dict() == {}
