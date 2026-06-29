"""Step 7 regression tests: single-container Docker + static SPA serving.

Focused on the catch-all SPA fallback behaviour:
- Unregistered ``/api/<path>`` → 404 JSON (must NOT return SPA HTML).
- SPA client-side routes (e.g. ``/some/spa/route``) → 200 + index.html.
- Registered API route (``/api/health``) → 200 JSON (unchanged).

Static serving is only activated when the built static directory exists at
``backend/static/``.  In the normal test run that directory is absent, so the
catch-all is never registered and the tests above would trivially pass (or
even miss the bug).  To exercise the real code path these tests create a
temporary directory containing a minimal ``index.html``, monkeypatch the
module-level ``app.main._STATIC_DIR`` to point at it, and rebuild the app.
The temp dir is cleaned up automatically via ``tmp_path`` (pytest built-in).
"""

import os
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient  # noqa: E402

from tests.conftest import drop_all_sqlite

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_temp_db_url() -> tuple[str, Path]:
    """Return a (url, path) pair for a fresh temp-file SQLite DB."""
    fd, path_str = tempfile.mkstemp(suffix=".db", prefix="omniventory_step7_")
    os.close(fd)
    path = Path(path_str)
    path.unlink()  # Start empty; SQLAlchemy will create it.
    return f"sqlite:///{path_str}", path


@pytest.fixture()
def static_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Generator[TestClient]:
    """TestClient with static serving active against a temp directory.

    Steps:
    1. Create a minimal ``static/`` tree under ``tmp_path`` (just ``index.html``
       and an ``assets/`` subdirectory so StaticFiles mounts don't error).
    2. Monkeypatch ``app.main._STATIC_DIR`` to point at that temp dir.
    3. Set the required env vars (SECRET_KEY, ENVIRONMENT=test, DATABASE_URL).
    4. Clear lru_cache singletons so the patched values take effect.
    5. Build a fresh app and yield a ``TestClient``.
    6. Teardown clears caches again; ``tmp_path`` is cleaned by pytest.
    """
    # --- Build minimal static tree -----------------------------------------
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html><html><body>SPA</body></html>")
    assets_dir = static_dir / "assets"
    assets_dir.mkdir()
    # A dummy asset so the /assets mount has at least one file.
    (assets_dir / "main.js").write_text("// bundle")
    # Service-worker and manifest files (non-content-hashed root files).
    (static_dir / "sw.js").write_text("// service worker")
    (static_dir / "registerSW.js").write_text("// register SW")
    (static_dir / "manifest.webmanifest").write_text("{}")
    (static_dir / "workbox-abc123.js").write_text("// workbox runtime")
    # A non-SW root file (icon) — must NOT receive no-cache.
    (static_dir / "icon-192.png").write_bytes(b"\x89PNG")

    # --- Patch module-level _STATIC_DIR BEFORE create_app() is called -------
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "_STATIC_DIR", static_dir)

    # --- Env / cache setup --------------------------------------------------
    url, db_path = _make_temp_db_url()
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-step7")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DATABASE_URL", url)

    from app.config import get_settings
    from app.db.base import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()

    # --- Create app + schema ------------------------------------------------
    from app.db.base import Base
    from app.main import create_app

    engine = get_engine()
    Base.metadata.create_all(engine)

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    # --- Teardown -----------------------------------------------------------
    drop_all_sqlite(Base, engine)
    get_settings.cache_clear()
    get_engine.cache_clear()
    if db_path.exists():
        db_path.unlink()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSpaFallbackWithStaticServing:
    """Catch-all SPA fallback behaviour when static serving is active."""

    def test_unregistered_api_path_returns_404_not_spa(self, static_client: TestClient) -> None:
        """GET /api/<nonexistent> must return 404, not 200 SPA HTML.

        This is the regression guard for the finding in M0-step7-review.md:
        the catch-all was swallowing unregistered /api/* paths and returning
        the SPA index.html with status 200.
        """
        response = static_client.get("/api/nonexistent")
        assert response.status_code == 404, (
            f"Expected 404 for unregistered /api/nonexistent but got {response.status_code}; "
            f"body: {response.text[:200]}"
        )
        # Must NOT return SPA HTML.
        assert "<!doctype html>" not in response.text.lower(), (
            "Unregistered /api/* path must not return SPA HTML"
        )

    def test_unregistered_api_nested_path_returns_404(self, static_client: TestClient) -> None:
        """GET /api/v99/deep/path also returns 404 (not SPA HTML)."""
        response = static_client.get("/api/v99/deep/path")
        assert response.status_code == 404

    def test_bare_api_prefix_returns_404(self, static_client: TestClient) -> None:
        """GET /api (no trailing slash) also returns 404."""
        response = static_client.get("/api")
        assert response.status_code == 404

    def test_spa_client_side_route_returns_index_html(self, static_client: TestClient) -> None:
        """GET /some/spa/route must return 200 with the SPA index.html content."""
        response = static_client.get("/some/spa/route")
        assert response.status_code == 200, (
            f"Expected 200 for SPA route but got {response.status_code}"
        )
        assert "<!doctype html>" in response.text.lower(), "SPA route must return index.html"

    def test_registered_api_health_still_returns_200(self, static_client: TestClient) -> None:
        """GET /api/health must still return 200 JSON (registered route unaffected)."""
        response = static_client.get("/api/health")
        assert response.status_code == 200, (
            f"Registered /api/health broken; got {response.status_code}"
        )
        body = response.json()
        assert body.get("status") == "ok"


class TestSpaCacheControlHeaders:
    """Cache-Control headers on the SPA shell and service-worker files.

    Regression guard for the stale-PWA bug: without ``no-cache`` the browser
    applies heuristic caching to ``index.html`` / ``sw.js`` so a normal
    Ctrl-R keeps showing the old build.  Content-hashed ``/assets/*`` bundles
    must NOT be flagged no-cache (they are immutable by filename).
    """

    def test_index_html_fallback_has_no_cache(self, static_client: TestClient) -> None:
        """GET / (SPA root) must respond with Cache-Control: no-cache."""
        response = static_client.get("/")
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "no-cache", (
            f"index.html fallback missing no-cache; got: {response.headers.get('cache-control')!r}"
        )

    def test_explicit_index_html_has_no_cache(self, static_client: TestClient) -> None:
        """GET /index.html (explicit exact-file path) must also respond with Cache-Control: no-cache.

        The fallback path always sets no-cache, but an explicit request for
        /index.html goes through the exact-file branch where _spa_cache_headers
        is called.  This test ensures "index.html" is covered there too, so
        both access paths are consistent.
        """
        response = static_client.get("/index.html")
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "no-cache", (
            f"explicit GET /index.html missing no-cache; got: {response.headers.get('cache-control')!r}"
        )

    def test_spa_client_route_index_html_has_no_cache(self, static_client: TestClient) -> None:
        """GET /shopping-list (any SPA route) must also carry Cache-Control: no-cache."""
        response = static_client.get("/shopping-list")
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "no-cache", (
            f"SPA route index.html missing no-cache; got: {response.headers.get('cache-control')!r}"
        )

    def test_sw_js_has_no_cache(self, static_client: TestClient) -> None:
        """GET /sw.js must respond with Cache-Control: no-cache."""
        response = static_client.get("/sw.js")
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "no-cache", (
            f"sw.js missing no-cache; got: {response.headers.get('cache-control')!r}"
        )

    def test_register_sw_js_has_no_cache(self, static_client: TestClient) -> None:
        """GET /registerSW.js must respond with Cache-Control: no-cache."""
        response = static_client.get("/registerSW.js")
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "no-cache", (
            f"registerSW.js missing no-cache; got: {response.headers.get('cache-control')!r}"
        )

    def test_webmanifest_has_no_cache(self, static_client: TestClient) -> None:
        """GET /manifest.webmanifest must respond with Cache-Control: no-cache."""
        response = static_client.get("/manifest.webmanifest")
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "no-cache", (
            f"manifest.webmanifest missing no-cache; got: {response.headers.get('cache-control')!r}"
        )

    def test_workbox_chunk_has_no_cache(self, static_client: TestClient) -> None:
        """GET /workbox-<hash>.js must respond with Cache-Control: no-cache."""
        response = static_client.get("/workbox-abc123.js")
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "no-cache", (
            f"workbox chunk missing no-cache; got: {response.headers.get('cache-control')!r}"
        )

    def test_icon_does_not_have_no_cache(self, static_client: TestClient) -> None:
        """GET /icon-192.png (non-SW root file) must NOT carry Cache-Control: no-cache."""
        response = static_client.get("/icon-192.png")
        assert response.status_code == 200
        assert response.headers.get("cache-control") != "no-cache", (
            "icon-192.png should not receive no-cache (leave to browser default)"
        )

    def test_assets_bundle_does_not_have_no_cache(self, static_client: TestClient) -> None:
        """GET /assets/main.js (content-hashed bundle) must NOT carry Cache-Control: no-cache.

        Content-hashed assets are immutable by filename and must stay fully
        cacheable; no-cache would break their long-lived caching contract.
        """
        response = static_client.get("/assets/main.js")
        assert response.status_code == 200
        assert response.headers.get("cache-control") != "no-cache", (
            "/assets/* bundles must not receive no-cache (they are content-hashed)"
        )
