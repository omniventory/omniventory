"""Tests for M6 Step 7: auth rate limiting, SSRF guard, media auth, sliding sessions.

Coverage
--------
Rate limiting (unit — RateLimiter class with injectable fake clock):
- N=5 failures within the window are allowed; the (N+1)th triggers lockout
  so the request AFTER that returns 429 with Retry-After header and
  params.retry_after_seconds.
- Lockout duration doubles per subsequent violation and is capped at 1800s.
- A success (clear()) resets the counter; the next N failures are allowed again.
- The limiter is per-(scope, key): one key's lockout does not affect another.
- Lockout expires when the clock advances past lockout_until.

Rate limiting (integration — HTTP round-trips via TestClient):
- N failed logins from same IP → next login returns 429 (auth.rate_limited)
  with Retry-After header and retry_after_seconds in params.
- A successful login clears the counter.

SSRF guard (unit — validate_outbound_url / validate_broker_host):
- http://127.0.0.1 → UnsafeUrlError (loopback)
- http://169.254.169.254/latest/meta-data/ → UnsafeUrlError (link-local / APIPA)
- http://[::1]/ → UnsafeUrlError (IPv6 loopback)
- hostname that resolves to loopback (monkeypatched getaddrinfo) → UnsafeUrlError
- ftp://example.com → UnsafeUrlError (disallowed scheme)
- URL with no host (http:///path) → UnsafeUrlError
- public IP (monkeypatched to 1.2.3.4) → allowed (no exception)
- private LAN 192.168.1.1 → allowed
- private LAN 10.0.0.1 → allowed
- DNS resolution failure → UnsafeUrlError
- validate_broker_host with private LAN host → allowed
- validate_broker_host with loopback → rejected

Webhook SSRF integration:
- _deliver_one skips and records 'failed' delivery for a rejected URL.
- The httpx.Client is constructed with follow_redirects=False.

/media auth:
- GET /media/<shard>/<digest> without a session → 401 auth.not_authenticated
- GET /media/<shard>/<digest> with a valid session → file bytes, correct
  content_type header, and X-Content-Type-Options: nosniff.

Sliding-window session expiry:
- A session verify() within the refresh threshold (< TTL/2 remaining)
  extends expires_at and last_seen_at; re-reading from DB confirms the
  change was committed via a successful round-trip request.
- A session with ample TTL (> TTL/2 remaining) does NOT update expires_at.
- An expired session returns None / 401 (unchanged).
"""

from __future__ import annotations

import hashlib
import importlib
import os
import socket
import tempfile
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import sessionmaker as SM

from tests.conftest import drop_all_sqlite

# ---------------------------------------------------------------------------
# Shared fixtures (same pattern as other M6 step tests)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_caches() -> Generator[None]:
    from app.config import get_settings
    from app.db.base import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.fixture()
def temp_db(monkeypatch: pytest.MonkeyPatch) -> Generator[Path]:
    fd, path_str = tempfile.mkstemp(suffix=".db", prefix="omniventory_m6_step7_")
    os.close(fd)
    db_path = Path(path_str)
    db_path.unlink()
    url = f"sqlite:///{path_str}"
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-m6-step7")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DATABASE_URL", url)
    yield db_path
    if db_path.exists():
        db_path.unlink()


def _reload_all_models() -> None:
    import app.db.base as db_base_mod
    import app.models.app_config as app_config_mod
    import app.models.attachment as attachment_mod
    import app.models.audit_log as audit_log_mod
    import app.models.barcode as barcode_mod
    import app.models.category as cat_mod
    import app.models.household as hh_mod
    import app.models.item_definition as idef_mod
    import app.models.item_kind as ikind_mod
    import app.models.location as loc_mod
    import app.models.media_file as media_file_mod
    import app.models.note as note_mod
    import app.models.notification as notif_mod
    import app.models.session as sess_mod
    import app.models.setting as setting_mod
    import app.models.stock_instance as stock_instance_mod
    import app.models.stock_movement as stock_movement_mod
    import app.models.tag as tag_mod
    import app.models.user as user_mod
    import app.models.user_token as user_token_mod

    importlib.reload(db_base_mod)
    importlib.reload(hh_mod)
    importlib.reload(user_mod)
    importlib.reload(sess_mod)
    importlib.reload(app_config_mod)
    importlib.reload(cat_mod)
    importlib.reload(ikind_mod)
    importlib.reload(idef_mod)
    importlib.reload(stock_instance_mod)
    importlib.reload(stock_movement_mod)
    importlib.reload(loc_mod)
    importlib.reload(setting_mod)
    importlib.reload(notif_mod)
    importlib.reload(media_file_mod)
    importlib.reload(attachment_mod)
    importlib.reload(tag_mod)
    importlib.reload(note_mod)
    importlib.reload(barcode_mod)
    importlib.reload(user_token_mod)
    importlib.reload(audit_log_mod)


@pytest.fixture()
def base_client(
    temp_db: Path,  # noqa: ARG001
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, object]]:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _reload_all_models()

    from app.config import get_settings
    from app.db.base import Base, get_engine
    from app.main import create_app

    get_settings.cache_clear()
    engine = get_engine()
    Base.metadata.create_all(engine)
    app = create_app()

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, engine

    drop_all_sqlite(Base, engine)


# ---------------------------------------------------------------------------
# DB helpers (same pattern as other M6 step tests)
# ---------------------------------------------------------------------------


def _make_user(
    engine: object,
    email: str,
    role: str = "admin",
    is_active: bool = True,
    password: str = "testpassword",
) -> int:
    factory = SM(bind=engine, autocommit=False, autoflush=False)  # type: ignore[arg-type]
    db: DBSession = factory()
    try:
        from app.auth.passwords import hash_password
        from app.repositories.user import UserRepository

        repo = UserRepository(db)
        user = repo.create(
            email=email,
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
        )
        db.commit()
        return user.id
    finally:
        db.close()


def _login(client: TestClient, email: str, password: str = "testpassword") -> None:
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, f"Login failed for {email}: {resp.json()}"


def _setup_admin(
    base_client: tuple[TestClient, object],
    email: str = "admin@example.com",
    password: str = "testpassword",
) -> tuple[TestClient, int]:
    client, engine = base_client
    uid = _make_user(engine, email, role="admin", password=password)
    _login(client, email, password)
    return client, uid


# ===========================================================================
# Section 1: Rate Limiting — unit tests (injectable clock, no HTTP)
# ===========================================================================


class TestRateLimiterUnit:
    """Unit tests for RateLimiter with an injectable fake clock."""

    def _make_limiter(self, start: float = 0.0):  # type: ignore[type-arg]
        """Return (limiter, clock_list) where clock_list[0] is the current time."""
        from app.core.rate_limit import RateLimiter

        t: list[float] = [start]
        limiter = RateLimiter(now=lambda: t[0])
        return limiter, t

    def test_n_failures_all_reach_handler_no_429(self) -> None:
        """All N=5 failures reach the handler (check() passes each time).

        The sequence for each failing request: check() → passes → handler runs
        → fails → register_failure().  After exactly N failures, lockout is
        imposed (on the Nth register_failure call), so the (N+1)th check raises.
        This test verifies that all N check() calls pass — i.e. no premature 429.
        """
        from app.core.rate_limit import _THRESHOLD

        limiter, _t = self._make_limiter()
        for _ in range(_THRESHOLD):
            # check() must pass (no lockout yet at this point)
            limiter.check("login", "1.2.3.4")  # should NOT raise
            # Simulate a failed attempt (handler returned 401)
            limiter.register_failure("login", "1.2.3.4")
        # After N failures the lockout IS now imposed; verified below.

    def test_n_plus_one_check_raises_429(self) -> None:
        """After N failures trigger lockout, the (N+1)th check raises 429."""
        from app.core.errors import AppError, ErrorCode
        from app.core.rate_limit import _THRESHOLD

        limiter, _t = self._make_limiter()
        # Simulate N complete request cycles (check → register_failure)
        for _ in range(_THRESHOLD):
            limiter.check("login", "1.2.3.4")
            limiter.register_failure("login", "1.2.3.4")

        # The (N+1)th check should raise 429
        with pytest.raises(AppError) as exc_info:
            limiter.check("login", "1.2.3.4")
        assert exc_info.value.code == ErrorCode.AUTH_RATE_LIMITED
        assert exc_info.value.status_code == 429
        assert exc_info.value.headers is not None
        assert "Retry-After" in exc_info.value.headers
        assert exc_info.value.params is not None
        assert "retry_after_seconds" in exc_info.value.params

    def test_lockout_doubles_per_violation(self) -> None:
        """Lockout duration doubles for each subsequent violation."""
        from app.core.errors import AppError
        from app.core.rate_limit import _THRESHOLD, RateLimiter

        t: list[float] = [0.0]
        limiter = RateLimiter(now=lambda: t[0])

        def _trigger_lockout() -> None:
            """Cause N complete request cycles to impose a new lockout."""
            # Advance past any existing lockout first so check() passes
            t[0] += 10_000.0
            # N check+register cycles trigger lockout on the Nth register
            for _ in range(_THRESHOLD):
                limiter.check("login", "1.2.3.4")  # must not raise
                limiter.register_failure("login", "1.2.3.4")

        _trigger_lockout()  # 1st violation
        t[0] += 1.0  # advance 1s (still within lockout)
        with pytest.raises(AppError) as exc1:
            limiter.check("login", "1.2.3.4")
        retry1 = exc1.value.params["retry_after_seconds"]  # type: ignore[index]
        assert retry1 > 0

        # Advance past the 1st lockout
        _trigger_lockout()  # 2nd violation — should be longer lockout
        t[0] += 1.0
        with pytest.raises(AppError) as exc2:
            limiter.check("login", "1.2.3.4")
        retry2 = exc2.value.params["retry_after_seconds"]  # type: ignore[index]
        assert retry2 > retry1, f"2nd lockout ({retry2}s) should > 1st ({retry1}s)"

        # Advance past the 2nd lockout
        _trigger_lockout()  # 3rd violation
        t[0] += 1.0
        with pytest.raises(AppError) as exc3:
            limiter.check("login", "1.2.3.4")
        retry3 = exc3.value.params["retry_after_seconds"]  # type: ignore[index]
        assert retry3 >= retry2

    def test_lockout_is_capped(self) -> None:
        """Lockout never exceeds _CAP seconds."""
        from app.core.errors import AppError
        from app.core.rate_limit import _CAP, _THRESHOLD, RateLimiter

        t: list[float] = [0.0]
        limiter = RateLimiter(now=lambda: t[0])

        # Trigger many violations to force the cap
        for _ in range(30):
            t[0] += 10_000.0  # advance past any previous lockout
            for _ in range(_THRESHOLD):
                limiter.check("login", "1.2.3.4")  # passes (past lockout)
                limiter.register_failure("login", "1.2.3.4")

        t[0] += 1.0
        with pytest.raises(AppError) as exc_info:
            limiter.check("login", "1.2.3.4")
        retry = exc_info.value.params["retry_after_seconds"]  # type: ignore[index]
        assert retry <= _CAP + 1, f"Lockout {retry}s exceeds cap {_CAP}s"

    def test_success_clears_counter(self) -> None:
        """A clear() call resets failures; the next N failures are allowed again."""
        from app.core.errors import AppError
        from app.core.rate_limit import _THRESHOLD

        limiter, _t = self._make_limiter()
        # Complete N-1 request cycles (no lockout yet)
        for _ in range(_THRESHOLD - 1):
            limiter.check("login", "1.2.3.4")
            limiter.register_failure("login", "1.2.3.4")
        # Simulate a success → clear counter
        limiter.clear("login", "1.2.3.4")
        # Now can complete N full cycles without lockout triggered on check
        for _ in range(_THRESHOLD):
            limiter.check("login", "1.2.3.4")  # should NOT raise
            limiter.register_failure("login", "1.2.3.4")
        # After N failures from a fresh start, the Nth imposed lockout.
        # Confirm (N+1)th check raises 429.
        with pytest.raises(AppError):
            limiter.check("login", "1.2.3.4")

    def test_per_key_isolation(self) -> None:
        """Lockout on one key does not affect a different key."""
        from app.core.errors import AppError
        from app.core.rate_limit import _THRESHOLD

        limiter, _t = self._make_limiter()
        # Trigger lockout for key A (N complete cycles)
        for _ in range(_THRESHOLD):
            limiter.check("login", "key_a")
            limiter.register_failure("login", "key_a")
        # Key A is locked
        with pytest.raises(AppError):
            limiter.check("login", "key_a")
        # Key B is unaffected
        limiter.check("login", "key_b")  # should not raise

    def test_lockout_expires_with_clock(self) -> None:
        """Lockout expires when the clock advances past lockout_until."""
        from app.core.rate_limit import _BASE_LOCKOUT, _THRESHOLD, RateLimiter

        t: list[float] = [0.0]
        limiter = RateLimiter(now=lambda: t[0])
        # Trigger lockout (N complete cycles)
        for _ in range(_THRESHOLD):
            limiter.check("login", "1.2.3.4")
            limiter.register_failure("login", "1.2.3.4")
        # Advance past the lockout
        t[0] = _BASE_LOCKOUT + 1.0
        limiter.check("login", "1.2.3.4")  # should NOT raise

    def test_window_trims_old_failures(self) -> None:
        """Failures older than the rolling window don't count toward lockout."""
        from app.core.rate_limit import _THRESHOLD, _WINDOW, RateLimiter

        t: list[float] = [0.0]
        limiter = RateLimiter(now=lambda: t[0])
        # Record N-1 failures (not enough to trigger lockout)
        for _ in range(_THRESHOLD - 1):
            limiter.check("login", "1.2.3.4")
            limiter.register_failure("login", "1.2.3.4")
        # Advance past the window — old failures now expired
        t[0] = _WINDOW + 1.0
        # N more failures from this new time → only the new ones count.
        # (N-1) old failures are outside window, so only fresh ones matter.
        # After N fresh check+register cycles, lockout triggers.
        # Before that, all checks should pass.
        for _ in range(_THRESHOLD - 1):
            limiter.check("login", "1.2.3.4")  # should NOT raise
            limiter.register_failure("login", "1.2.3.4")

    def test_different_scopes_independent(self) -> None:
        """Different scopes are independent even for the same key."""
        from app.core.errors import AppError
        from app.core.rate_limit import _THRESHOLD

        limiter, _t = self._make_limiter()
        for _ in range(_THRESHOLD):
            limiter.check("login", "1.2.3.4")
            limiter.register_failure("login", "1.2.3.4")
        # "login" scope locked
        with pytest.raises(AppError):
            limiter.check("login", "1.2.3.4")
        # "setup" scope unaffected
        limiter.check("setup", "1.2.3.4")  # should not raise

    def test_reset_clears_all(self) -> None:
        """reset() clears all state across all keys."""
        from app.core.errors import AppError
        from app.core.rate_limit import _THRESHOLD

        limiter, _t = self._make_limiter()
        for _ in range(_THRESHOLD):
            limiter.check("login", "1.2.3.4")
            limiter.register_failure("login", "1.2.3.4")
        # Confirm locked before reset
        with pytest.raises(AppError):
            limiter.check("login", "1.2.3.4")
        limiter.reset()
        # After reset, check should pass again
        limiter.check("login", "1.2.3.4")  # should not raise


# ===========================================================================
# Section 2: Rate Limiting — HTTP integration tests
# ===========================================================================


class TestRateLimitHttp:
    """Integration tests for rate limiting via the TestClient."""

    def test_login_rate_limited_after_n_failures(
        self, base_client: tuple[TestClient, object]
    ) -> None:
        """N failed logins trigger lockout; the (N+1)th request gets 429.

        Sequence:
        - Requests 1 through N: check() passes, handler fails (401),
          register_failure() called.  On the Nth register_failure, lockout
          is imposed (>= threshold).
        - Request N+1: check() raises 429 auth.rate_limited with Retry-After.
        """
        from app.core.rate_limit import _THRESHOLD

        client, engine = base_client
        _make_user(engine, "ratetest@example.com", role="admin")

        # N failing login attempts (all should return 401)
        for i in range(_THRESHOLD):
            resp = client.post(
                "/api/auth/login",
                json={"email": "ratetest@example.com", "password": "wrongpass"},
            )
            assert resp.status_code == 401, f"Attempt {i + 1}: expected 401, got {resp.status_code}"

        # The (N+1)th request should be blocked by the rate limiter (429)
        resp_429 = client.post(
            "/api/auth/login",
            json={"email": "ratetest@example.com", "password": "wrongpass"},
        )
        assert resp_429.status_code == 429
        body = resp_429.json()
        assert body["code"] == "auth.rate_limited"
        assert "Retry-After" in resp_429.headers
        assert body["params"]["retry_after_seconds"] > 0

    def test_successful_login_clears_rate_limit(
        self, base_client: tuple[TestClient, object]
    ) -> None:
        """N-1 failures followed by a success clears the counter.

        After clear(), the next N-1 failures should again be allowed (401, not 429).
        """
        from app.core.rate_limit import _THRESHOLD

        client, engine = base_client
        _make_user(engine, "cleartest@example.com", role="admin")

        # N-1 failures (below threshold → no lockout)
        for _ in range(_THRESHOLD - 1):
            r = client.post(
                "/api/auth/login",
                json={"email": "cleartest@example.com", "password": "wrongpass"},
            )
            assert r.status_code == 401

        # Successful login → clears counter
        resp = client.post(
            "/api/auth/login",
            json={"email": "cleartest@example.com", "password": "testpassword"},
        )
        assert resp.status_code == 200

        # Can now fail N-1 more times without 429 (counter was reset)
        for i in range(_THRESHOLD - 1):
            r = client.post(
                "/api/auth/login",
                json={"email": "cleartest@example.com", "password": "wrongpass"},
            )
            assert r.status_code == 401, (
                f"Post-clear attempt {i + 1}: expected 401, got {r.status_code}"
            )

    def test_429_response_has_retry_after_header(
        self, base_client: tuple[TestClient, object]
    ) -> None:
        """The 429 response includes Retry-After header and params.retry_after_seconds."""
        from app.core.rate_limit import _THRESHOLD

        client, engine = base_client
        _make_user(engine, "header_test@example.com", role="admin")

        # N failures trigger lockout; (N+1)th gets 429
        for _ in range(_THRESHOLD):
            client.post(
                "/api/auth/login",
                json={"email": "header_test@example.com", "password": "wrong"},
            )

        resp = client.post(
            "/api/auth/login",
            json={"email": "header_test@example.com", "password": "wrong"},
        )
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        assert int(resp.headers["Retry-After"]) > 0
        assert resp.json()["params"]["retry_after_seconds"] > 0


# ===========================================================================
# Section 3: SSRF Guard — unit tests
# ===========================================================================


class TestSsrfGuardUnit:
    """Unit tests for validate_outbound_url and validate_broker_host."""

    def test_loopback_ipv4_rejected(self) -> None:
        """http://127.0.0.1 is rejected (loopback)."""
        from app.core.net_guard import UnsafeUrlError, validate_outbound_url

        with pytest.raises(UnsafeUrlError):
            validate_outbound_url("http://127.0.0.1/data")

    def test_apipa_link_local_rejected(self) -> None:
        """http://169.254.169.254 is rejected (link-local / AWS metadata)."""
        from app.core.net_guard import UnsafeUrlError, validate_outbound_url

        with pytest.raises(UnsafeUrlError):
            validate_outbound_url("http://169.254.169.254/latest/meta-data/")

    def test_ipv6_loopback_rejected(self) -> None:
        """http://[::1]/ is rejected (IPv6 loopback)."""
        from app.core.net_guard import UnsafeUrlError, validate_outbound_url

        with pytest.raises(UnsafeUrlError):
            validate_outbound_url("http://[::1]/")

    def test_hostname_resolving_to_loopback_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A hostname that resolves to 127.0.0.1 is rejected after DNS lookup."""
        from app.core.net_guard import UnsafeUrlError, validate_outbound_url

        # Patch socket.getaddrinfo to return loopback for "evil.example.com"
        def _fake_getaddrinfo(
            host: str,
            port: object,
            *args: object,
            **kwargs: object,
        ) -> list[object]:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]

        monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
        with pytest.raises(UnsafeUrlError):
            validate_outbound_url("http://evil.example.com/webhook")

    def test_ftp_scheme_rejected(self) -> None:
        """ftp://example.com is rejected (disallowed scheme)."""
        from app.core.net_guard import UnsafeUrlError, validate_outbound_url

        with pytest.raises(UnsafeUrlError):
            validate_outbound_url("ftp://example.com/resource")

    def test_missing_host_rejected(self) -> None:
        """A URL with no host component is rejected."""
        from app.core.net_guard import UnsafeUrlError, validate_outbound_url

        with pytest.raises(UnsafeUrlError):
            validate_outbound_url("http:///path/only")

    def test_dns_failure_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DNS resolution failure causes rejection."""
        import socket as socket_mod

        from app.core.net_guard import UnsafeUrlError, validate_outbound_url

        def _raise_gaierror(*args: object, **kwargs: object) -> list[object]:
            raise socket_mod.gaierror("Name or service not known")

        monkeypatch.setattr(socket_mod, "getaddrinfo", _raise_gaierror)
        with pytest.raises(UnsafeUrlError):
            validate_outbound_url("http://nonexistent.internal.example/hook")

    def test_public_ip_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A URL resolving to a public IP is allowed."""
        from app.core.net_guard import validate_outbound_url

        def _fake_getaddrinfo(
            host: str,
            port: object,
            *args: object,
            **kwargs: object,
        ) -> list[object]:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("1.2.3.4", 0))]

        monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
        validate_outbound_url("https://hooks.example.com/webhook")  # should not raise

    def test_private_lan_192168_allowed(self) -> None:
        """192.168.x.x (RFC 1918 private LAN) is allowed."""
        from app.core.net_guard import validate_outbound_url

        def _fake_getaddrinfo(
            host: str,
            port: object,
            *args: object,
            **kwargs: object,
        ) -> list[object]:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.100", 0))]

        with patch("socket.getaddrinfo", _fake_getaddrinfo):
            validate_outbound_url("http://homeassistant.local/api/webhook/abc")  # should not raise

    def test_private_lan_10x_allowed(self) -> None:
        """10.x.x.x (RFC 1918 private LAN) is allowed."""
        from app.core.net_guard import validate_outbound_url

        def _fake_getaddrinfo(
            host: str,
            port: object,
            *args: object,
            **kwargs: object,
        ) -> list[object]:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", 0))]

        with patch("socket.getaddrinfo", _fake_getaddrinfo):
            validate_outbound_url("http://server.lan/hook")  # should not raise

    def test_broker_host_loopback_rejected(self) -> None:
        """validate_broker_host rejects 127.0.0.1."""
        from app.core.net_guard import UnsafeUrlError, validate_broker_host

        with pytest.raises(UnsafeUrlError):
            validate_broker_host("127.0.0.1")

    def test_broker_host_private_lan_allowed(self) -> None:
        """validate_broker_host allows 192.168.x.x."""
        from app.core.net_guard import validate_broker_host

        def _fake_getaddrinfo(
            host: str,
            port: object,
            *args: object,
            **kwargs: object,
        ) -> list[object]:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.5", 0))]

        with patch("socket.getaddrinfo", _fake_getaddrinfo):
            validate_broker_host("mqtt.home.local")  # should not raise

    def test_broker_host_empty_rejected(self) -> None:
        """validate_broker_host rejects empty/blank host."""
        from app.core.net_guard import UnsafeUrlError, validate_broker_host

        with pytest.raises(UnsafeUrlError):
            validate_broker_host("")
        with pytest.raises(UnsafeUrlError):
            validate_broker_host("   ")


class TestWebhookSsrfIntegration:
    """Tests that the HttpChannel wires the SSRF guard and follow_redirects=False."""

    def test_deliver_one_records_failed_for_blocked_url(self) -> None:
        """_deliver_one skips the POST and records 'failed' for a loopback URL."""
        # We test at the HttpChannel level — no real DB, no real HTTP.
        # Patch the delivery repo and user repo to avoid needing a full DB.

        from app.notifications.channels.http import HttpChannel

        channel = HttpChannel.__new__(HttpChannel)

        mock_delivery_repo = MagicMock()
        mock_delivery_repo.exists_sent.return_value = False
        channel._delivery_repo = mock_delivery_repo

        mock_user_repo = MagicMock()
        mock_user_repo.get_by_id.return_value = MagicMock(preferred_language="en")
        channel._user_repo = mock_user_repo

        mock_notification = MagicMock()
        mock_notification.id = 42
        mock_notification.user_id = 1
        mock_notification.params = None
        mock_notification.message_code = "reminder.best_before"

        # Use a blocked URL (loopback)
        channel._deliver_one(mock_notification, "http://127.0.0.1/hook", None)

        # Should record a 'failed' delivery, not 'sent'
        mock_delivery_repo.record.assert_called_once()
        call_kwargs = mock_delivery_repo.record.call_args
        assert call_kwargs.kwargs["status"] == "failed"

    def test_http_client_uses_follow_redirects_false(self) -> None:
        """The httpx.Client is constructed with follow_redirects=False."""
        from unittest.mock import patch

        from app.notifications.channels.http import HttpChannel

        channel = HttpChannel.__new__(HttpChannel)

        mock_delivery_repo = MagicMock()
        mock_delivery_repo.exists_sent.return_value = False
        channel._delivery_repo = mock_delivery_repo

        mock_user_repo = MagicMock()
        mock_user_repo.get_by_id.return_value = MagicMock(preferred_language="en")
        channel._user_repo = mock_user_repo

        mock_notification = MagicMock()
        mock_notification.id = 1
        mock_notification.user_id = 1
        mock_notification.params = None
        mock_notification.message_code = "reminder.best_before"

        captured_init_kwargs: dict[str, object] = {}

        class MockResponse:
            status_code = 200

            def raise_for_status(self) -> None:
                pass

        class MockClient:
            def __init__(self, **kwargs: object) -> None:
                captured_init_kwargs.update(kwargs)

            def __enter__(self) -> MockClient:
                return self

            def __exit__(self, *args: object) -> None:
                pass

            def post(self, *args: object, **kwargs: object) -> MockResponse:
                return MockResponse()

        # Monkeypatch getaddrinfo to allow the URL
        def _public_ip(*args: object, **kwargs: object) -> list[object]:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("1.2.3.4", 0))]

        with (
            patch("socket.getaddrinfo", _public_ip),
            patch("app.notifications.channels.http.httpx.Client", MockClient),
        ):
            channel._deliver_one(mock_notification, "https://hooks.example.com/wh", None)

        assert "follow_redirects" in captured_init_kwargs
        assert captured_init_kwargs["follow_redirects"] is False


# ===========================================================================
# Section 4: /media authentication
# ===========================================================================


class TestMediaAuth:
    """Tests that /media requires a valid session."""

    @pytest.fixture()
    def media_client(
        self,
        temp_db: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> Generator[tuple[TestClient, object, Path]]:
        """TestClient with schema + isolated media dir, no pre-auth."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        _reload_all_models()

        from app.config import get_settings
        from app.db.base import Base, get_engine
        from app.main import create_app

        get_settings.cache_clear()
        engine = get_engine()
        Base.metadata.create_all(engine)
        app = create_app()

        with TestClient(app, raise_server_exceptions=True) as client:
            yield client, engine, tmp_path

        drop_all_sqlite(Base, engine)

    def _create_media_file_on_disk(
        self,
        engine: object,
        tmp_path: Path,
        content: bytes = b"fake-image-content",
        content_type: str = "image/jpeg",
    ) -> tuple[str, str]:
        """Insert a media_files row and write the file on disk.

        Returns (shard, digest) for the /media/<shard>/<digest> URL.
        """

        digest = hashlib.sha256(content).hexdigest()
        shard = digest[:2]

        # Write the file on disk
        media_dir = tmp_path / "media" / shard
        media_dir.mkdir(parents=True, exist_ok=True)
        (media_dir / digest).write_bytes(content)

        # Insert the media_files row
        factory = SM(bind=engine, autocommit=False, autoflush=False)  # type: ignore[arg-type]
        db: DBSession = factory()
        try:
            from app.models.media_file import MediaFile

            mf = MediaFile(
                sha256=digest,
                content_type=content_type,
                byte_size=len(content),
            )
            db.add(mf)
            db.commit()
        finally:
            db.close()

        return shard, digest

    def test_media_unauthenticated_returns_401(
        self, media_client: tuple[TestClient, object, Path]
    ) -> None:
        """GET /media/<shard>/<digest> without a session returns 401."""
        client, engine, tmp_path = media_client
        shard, digest = self._create_media_file_on_disk(engine, tmp_path)

        resp = client.get(f"/media/{shard}/{digest}")
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] in ("auth.not_authenticated", "auth.session_invalid")

    def test_media_authenticated_returns_file(
        self, media_client: tuple[TestClient, object, Path]
    ) -> None:
        """GET /media/<shard>/<digest> with a valid session returns the file."""
        client, engine, tmp_path = media_client
        content = b"fake-image-content-for-auth-test"
        shard, digest = self._create_media_file_on_disk(
            engine, tmp_path, content=content, content_type="image/jpeg"
        )

        # Create and log in as admin
        _make_user(engine, "media_admin@example.com", role="admin")
        _login(client, "media_admin@example.com")

        resp = client.get(f"/media/{shard}/{digest}")
        assert resp.status_code == 200
        assert resp.content == content
        assert resp.headers.get("content-type", "").startswith("image/jpeg")
        assert resp.headers.get("x-content-type-options") == "nosniff"

    def test_media_expired_session_returns_401(
        self, media_client: tuple[TestClient, object, Path]
    ) -> None:
        """GET /media/<shard>/<digest> after session expiry returns 401."""
        client, engine, tmp_path = media_client
        shard, digest = self._create_media_file_on_disk(engine, tmp_path)

        _make_user(engine, "media_expiry@example.com", role="admin")
        _login(client, "media_expiry@example.com")

        # Expire the session directly in the DB
        factory = SM(bind=engine, autocommit=False, autoflush=False)  # type: ignore[arg-type]
        db: DBSession = factory()
        try:
            from app.models.session import Session as SessionModel

            sessions = db.query(SessionModel).all()
            for sess in sessions:
                sess.expires_at = datetime.now(UTC) - timedelta(hours=1)
            db.commit()
        finally:
            db.close()

        resp = client.get(f"/media/{shard}/{digest}")
        assert resp.status_code == 401


# ===========================================================================
# Section 5: Sliding-window session expiry
# ===========================================================================


class TestSlidingWindowSession:
    """Tests that sessions.verify() extends expiry when near TTL/2 boundary."""

    def test_verify_extends_expiry_within_refresh_threshold(
        self, base_client: tuple[TestClient, object]
    ) -> None:
        """A session with < TTL/2 remaining has expires_at and last_seen_at extended."""
        from app.auth.sessions import SESSION_TTL_HOURS

        client, engine = base_client
        _make_user(engine, "sliding@example.com", role="admin")
        _login(client, "sliding@example.com")

        # Move the session's expires_at to just under TTL/2 remaining.
        # TTL = 24h, TTL/2 = 12h.  Set expires_at to now + 11h (under threshold).
        factory = SM(bind=engine, autocommit=False, autoflush=False)  # type: ignore[arg-type]
        db: DBSession = factory()
        try:
            from app.models.session import Session as SessionModel

            sessions = db.query(SessionModel).all()
            assert len(sessions) == 1
            sess = sessions[0]
            near_expiry = datetime.now(UTC) + timedelta(hours=SESSION_TTL_HOURS / 2 - 1)
            sess.expires_at = near_expiry
            original_expires_at = sess.expires_at
            db.commit()
        finally:
            db.close()

        # Make any authenticated request to trigger verify()
        resp = client.get("/api/auth/me")
        assert resp.status_code == 200

        # Re-read session from DB and verify expires_at was extended
        db = factory()
        try:
            from app.models.session import Session as SessionModel

            sessions = db.query(SessionModel).all()
            assert len(sessions) == 1
            sess = sessions[0]
            new_expires = sess.expires_at
            # New expiry should be approximately now + TTL (24h), definitely
            # more than the near_expiry we set.
            if new_expires.tzinfo is None:
                new_expires = new_expires.replace(tzinfo=UTC)
            if original_expires_at.tzinfo is None:
                original_expires_at = original_expires_at.replace(tzinfo=UTC)

            assert new_expires > original_expires_at, (
                f"expires_at should have been extended: "
                f"{new_expires} should > {original_expires_at}"
            )
            # Also check that the new expiry is approximately now + SESSION_TTL_HOURS
            expected_min = datetime.now(UTC) + timedelta(hours=SESSION_TTL_HOURS - 1)
            assert new_expires >= expected_min
        finally:
            db.close()

    def test_verify_does_not_write_with_ample_ttl(
        self, base_client: tuple[TestClient, object]
    ) -> None:
        """A session with > TTL/2 remaining does NOT update expires_at."""

        client, engine = base_client
        _make_user(engine, "ample@example.com", role="admin")
        _login(client, "ample@example.com")

        # Read the current expires_at (fresh session → plenty of TTL)
        factory = SM(bind=engine, autocommit=False, autoflush=False)  # type: ignore[arg-type]
        db: DBSession = factory()
        try:
            from app.models.session import Session as SessionModel

            sessions = db.query(SessionModel).all()
            assert len(sessions) == 1
            original_expires = sessions[0].expires_at
        finally:
            db.close()

        # Make an authenticated request
        resp = client.get("/api/auth/me")
        assert resp.status_code == 200

        # expires_at should be unchanged (≥ TTL/2 remaining → no write)
        db = factory()
        try:
            from app.models.session import Session as SessionModel

            sessions = db.query(SessionModel).all()
            assert len(sessions) == 1
            new_expires = sessions[0].expires_at
            # Compare timestamps — they should be equal (or within a tiny margin
            # caused by datetime round-trip through SQLite)
            orig = (
                original_expires
                if original_expires.tzinfo
                else original_expires.replace(tzinfo=UTC)
            )
            new = new_expires if new_expires.tzinfo else new_expires.replace(tzinfo=UTC)
            diff = abs((new - orig).total_seconds())
            assert diff < 2.0, f"expires_at changed by {diff}s when it should not have"
        finally:
            db.close()

    def test_expired_session_still_returns_401(
        self, base_client: tuple[TestClient, object]
    ) -> None:
        """An expired session returns 401 — sliding window doesn't resurrect it."""
        client, engine = base_client
        _make_user(engine, "expired@example.com", role="admin")
        _login(client, "expired@example.com")

        # Expire the session
        factory = SM(bind=engine, autocommit=False, autoflush=False)  # type: ignore[arg-type]
        db: DBSession = factory()
        try:
            from app.models.session import Session as SessionModel

            sessions = db.query(SessionModel).all()
            for sess in sessions:
                sess.expires_at = datetime.now(UTC) - timedelta(hours=1)
            db.commit()
        finally:
            db.close()

        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_sliding_window_unit_verify_refreshes(self) -> None:
        """Unit test: verify() flushes expires_at/last_seen_at within refresh threshold."""

        from app.auth import sessions as sess_mod
        from app.auth.sessions import SESSION_TTL_HOURS

        # Build a fake session ORM object

        now = datetime.now(UTC)
        half_ttl = timedelta(hours=SESSION_TTL_HOURS / 2)
        # expires_at is within the threshold (< TTL/2 remaining)
        near_expiry = now + half_ttl - timedelta(hours=1)

        mock_session = MagicMock()
        mock_session.expires_at = near_expiry  # tz-aware
        mock_session.last_seen_at = now - timedelta(hours=2)

        mock_db = MagicMock()
        mock_db.get.return_value = mock_session

        result = sess_mod.verify(mock_db, "fake_session_id")
        assert result is mock_session
        # flush should have been called (to persist the update)
        mock_db.flush.assert_called_once()
        # expires_at should be ~now + SESSION_TTL_HOURS
        assert mock_session.expires_at > now + timedelta(hours=SESSION_TTL_HOURS - 1)

    def test_sliding_window_unit_no_write_with_ample_ttl(self) -> None:
        """Unit test: verify() does NOT flush when TTL is ample."""

        from app.auth import sessions as sess_mod
        from app.auth.sessions import SESSION_TTL_HOURS

        now = datetime.now(UTC)
        half_ttl = timedelta(hours=SESSION_TTL_HOURS / 2)
        # expires_at is well within the safe zone (> TTL/2 remaining)
        ample_expiry = now + half_ttl + timedelta(hours=1)

        mock_session = MagicMock()
        mock_session.expires_at = ample_expiry
        original_expires = ample_expiry

        mock_db = MagicMock()
        mock_db.get.return_value = mock_session

        sess_mod.verify(mock_db, "fake_session_id")
        # flush should NOT have been called
        mock_db.flush.assert_not_called()
        assert mock_session.expires_at == original_expires

    def test_sliding_window_unit_expired_returns_none(self) -> None:
        """Unit test: verify() returns None for an expired session (no flush)."""

        from app.auth import sessions as sess_mod

        now = datetime.now(UTC)
        mock_session = MagicMock()
        mock_session.expires_at = now - timedelta(hours=1)  # expired

        mock_db = MagicMock()
        mock_db.get.return_value = mock_session

        result = sess_mod.verify(mock_db, "fake_session_id")
        assert result is None
        mock_db.flush.assert_not_called()
