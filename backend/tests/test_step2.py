"""Step 2 tests: app factory, settings, and health endpoint.

Covers:
- health endpoint: HTTP 200 + exact payload shape (status, version, api_version)
- settings load from environment variables
- missing secret_key raises a validation error (required field)
- api_prefix is configurable and changes the health endpoint mount point

Note: Step 3 extended the health endpoint to add ``db: "ok"``.  The fixtures
below therefore wire up a temp-file SQLite database so that the health
endpoint can perform its DB probe across threads.  Using a real file (not
:memory:) ensures the schema built in the fixture thread is visible to the
TestClient worker thread that executes route handlers.
"""

import os
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_settings_and_engine_cache() -> Generator[None]:
    """Clear lru_cache on get_settings and get_engine before/after every test."""
    from app.config import get_settings
    from app.db.base import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()


def _make_temp_db(monkeypatch: pytest.MonkeyPatch) -> tuple[str, Path]:
    """Create a temp-file SQLite DB, set DATABASE_URL, and return (url, path)."""
    fd, path_str = tempfile.mkstemp(suffix=".db", prefix="omniventory_step2_")
    os.close(fd)
    path = Path(path_str)
    path.unlink()  # Remove so the DB starts empty.
    url = f"sqlite:///{path_str}"
    monkeypatch.setenv("DATABASE_URL", url)
    return url, path


@pytest.fixture()
def default_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Set the minimum required environment variables for a valid Settings.

    Uses a temp-file SQLite (not :memory:) so the schema is shared across
    threads when TestClient drives requests through route handlers.
    """
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-unit-tests")
    _, db_path = _make_temp_db(monkeypatch)
    yield
    if db_path.exists():
        db_path.unlink()


@pytest.fixture()
def test_client(default_env: None) -> Generator[TestClient]:  # noqa: ARG001
    """Return a TestClient backed by a temp-file SQLite with the full schema."""
    from app.db.base import Base, get_engine
    from app.main import create_app

    engine = get_engine()
    Base.metadata.create_all(engine)
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    Base.metadata.drop_all(engine)


# ---------------------------------------------------------------------------
# Health endpoint tests
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """Tests for GET /api/health."""

    def test_health_returns_200(self, test_client: TestClient) -> None:
        """Health endpoint must return HTTP 200."""
        response = test_client.get("/api/health")
        assert response.status_code == 200

    def test_health_payload_shape(self, test_client: TestClient) -> None:
        """Health response must include status, version, and api_version.

        Note: Step 3 added ``db: "ok"`` to the response; this assertion now
        checks that the three original Step-2 keys are still present.
        """
        body = test_client.get("/api/health").json()

        # Required keys (present since Step 2)
        assert "status" in body
        assert "version" in body
        assert "api_version" in body

    def test_health_status_ok(self, test_client: TestClient) -> None:
        """Health status must be 'ok' while the process is running."""
        body = test_client.get("/api/health").json()
        assert body["status"] == "ok"

    def test_health_api_version_is_integer(self, test_client: TestClient) -> None:
        """api_version must be an integer."""
        body = test_client.get("/api/health").json()
        assert isinstance(body["api_version"], int)

    def test_health_version_is_string(self, test_client: TestClient) -> None:
        """version must be a non-empty string."""
        body = test_client.get("/api/health").json()
        assert isinstance(body["version"], str)
        assert len(body["version"]) > 0

    def test_health_under_custom_api_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Health must be reachable under a custom api_prefix."""
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("API_PREFIX", "/v1")
        _, db_path = _make_temp_db(monkeypatch)

        from app.db.base import Base, get_engine
        from app.main import create_app

        engine = get_engine()
        Base.metadata.create_all(engine)
        try:
            with TestClient(create_app()) as client:
                # Must be reachable under /v1/health
                assert client.get("/v1/health").status_code == 200
                # Must NOT be reachable under the default /api/health
                assert client.get("/api/health").status_code == 404
        finally:
            Base.metadata.drop_all(engine)
            if db_path.exists():
                db_path.unlink()

    def test_health_custom_api_version(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """api_version in the health response must reflect the configured value."""
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("API_VERSION", "42")
        _, db_path = _make_temp_db(monkeypatch)

        from app.db.base import Base, get_engine
        from app.main import create_app

        engine = get_engine()
        Base.metadata.create_all(engine)
        try:
            with TestClient(create_app()) as client:
                body = client.get("/api/health").json()
                assert body["api_version"] == 42
        finally:
            Base.metadata.drop_all(engine)
            if db_path.exists():
                db_path.unlink()


# ---------------------------------------------------------------------------
# Settings tests
# ---------------------------------------------------------------------------


class TestSettings:
    """Tests for app/config.py Settings."""

    def test_settings_load_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Settings must read field values from environment variables."""
        monkeypatch.setenv("SECRET_KEY", "env-loaded-secret")

        from app.config import Settings

        s = Settings()
        assert s.secret_key == "env-loaded-secret"

    def test_settings_api_prefix_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """api_prefix must default to '/api'."""
        monkeypatch.setenv("SECRET_KEY", "test-secret")

        from app.config import Settings

        s = Settings()
        assert s.api_prefix == "/api"

    def test_settings_missing_secret_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Constructing Settings without SECRET_KEY must raise a ValidationError."""
        # Ensure SECRET_KEY is NOT present in the environment for this test.
        monkeypatch.delenv("SECRET_KEY", raising=False)

        from app.config import Settings

        with pytest.raises(ValidationError) as exc_info:
            Settings()
        # Confirm the error mentions secret_key.
        assert "secret_key" in str(exc_info.value).lower()

    def test_settings_database_url_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """database_url must default to a SQLite URL."""
        monkeypatch.setenv("SECRET_KEY", "test-secret")

        from app.config import Settings

        s = Settings()
        assert s.database_url.startswith("sqlite")

    def test_settings_environment_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """environment must default to 'development'."""
        monkeypatch.setenv("SECRET_KEY", "test-secret")

        from app.config import Settings

        s = Settings()
        assert s.environment == "development"

    def test_get_settings_is_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_settings() must return the same object on repeated calls (lru_cache)."""
        monkeypatch.setenv("SECRET_KEY", "test-secret")

        from app.config import get_settings

        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2, "get_settings() must be cached (lru_cache)"

    def test_settings_session_cookie_name_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """session_cookie_name must have the correct default."""
        monkeypatch.setenv("SECRET_KEY", "test-secret")

        from app.config import Settings

        s = Settings()
        assert s.session_cookie_name == "omniventory_session"

    def test_settings_admin_bootstrap_defaults_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """admin_bootstrap_email and admin_bootstrap_password default to None."""
        monkeypatch.setenv("SECRET_KEY", "test-secret")

        from app.config import Settings

        s = Settings()
        assert s.admin_bootstrap_email is None
        assert s.admin_bootstrap_password is None
