"""Step 4 tests: session-cookie auth skeleton and admin bootstrap.

Required coverage (easy-to-get-wrong logic, per AGENTS.md / M0.md §9 Step 4):
- Password hash → verify (and wrong password fails).
- Session create → verify roundtrip.
- Expired session is rejected.
- Logout truly revokes (verify fails afterward).
- Cookie flags (HttpOnly, SameSite=Lax; Secure per environment policy).
- me is 401 without / 200 with a valid cookie.
- Bootstrap idempotent (running twice = exactly one admin).

Also covers:
- Migration 0002 applies clean on top of 0001 (via alembic subprocess).
- Migration 0002 downgrade is clean (reversible).
- UserRepository CRUD.
- Inactive user is rejected by get_current_user.
"""

import os
import tempfile
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base

# ---------------------------------------------------------------------------
# Helpers shared across fixtures
# ---------------------------------------------------------------------------


def _make_temp_db_url() -> tuple[str, Path]:
    """Return a (url, path) pair for a fresh temp-file SQLite DB."""
    fd, path_str = tempfile.mkstemp(suffix=".db", prefix="omniventory_step4_")
    os.close(fd)
    path = Path(path_str)
    path.unlink()  # Start empty.
    return f"sqlite:///{path_str}", path


def _make_in_memory_session() -> Session:
    """In-memory SQLite session with the full schema (single-thread unit tests).

    Reloads the model modules and re-imports Base to ensure all models are
    registered to the current Base.metadata.  This is necessary because
    test_step3's autouse fixture does ``importlib.reload(app.db.base)``
    after each test, creating a fresh Base with empty metadata; the model
    classes no longer reference that new Base until they are also reloaded.
    """
    import importlib

    from sqlalchemy import event

    # Re-sync the model metadata: reload db.base first (new Base + empty
    # metadata), then reload each model module so they re-register to it.
    import app.db.base as db_base_mod

    importlib.reload(db_base_mod)

    import app.models.household as hh_mod
    import app.models.session as sess_mod
    import app.models.user as user_mod

    importlib.reload(hh_mod)
    importlib.reload(user_mod)
    importlib.reload(sess_mod)

    from app.db.base import Base as _Base  # fresh Base with all tables

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enforce_fk(dbapi_conn: object, _: object) -> None:  # type: ignore[type-arg]
        import sqlite3

        if isinstance(dbapi_conn, sqlite3.Connection):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    _Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return factory()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_caches() -> Generator[None]:
    """Reset lru_cache on get_settings / get_engine before and after each test."""
    from app.config import get_settings
    from app.db.base import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.fixture()
def db_session() -> Generator[Session]:
    """Fresh in-memory SQLite session for pure unit tests."""
    session = _make_in_memory_session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def temp_db(monkeypatch: pytest.MonkeyPatch) -> Generator[Path]:
    """Temp-file SQLite; sets SECRET_KEY, ENVIRONMENT=test, DATABASE_URL."""
    url, db_path = _make_temp_db_url()
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-unit-tests")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DATABASE_URL", url)
    yield db_path
    if db_path.exists():
        db_path.unlink()


@pytest.fixture()
def test_client(temp_db: Path) -> Generator[TestClient]:  # noqa: ARG001
    """TestClient with a temp-file SQLite and the full schema applied.

    ``ENVIRONMENT=test`` is set by ``temp_db``, so the login route will NOT
    set ``Secure`` on the cookie.  This lets TestClient (HTTP) store and
    resend the cookie in subsequent requests (e.g. for /auth/me).
    """
    from app.db.base import get_engine
    from app.main import create_app

    engine = get_engine()
    Base.metadata.create_all(engine)
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    Base.metadata.drop_all(engine)


# ---------------------------------------------------------------------------
# Helper: create a user + session directly in the DB (bypasses HTTP layer)
# ---------------------------------------------------------------------------


def _create_user_and_session(
    db: Session,
    email: str = "test@example.com",
    password: str = "hunter2",
) -> tuple[int, str]:
    """Insert a User and a fresh Session; return (user_id, session_id)."""
    from app.auth.passwords import hash_password
    from app.auth.sessions import create as create_session
    from app.repositories.user import UserRepository

    repo = UserRepository(db)
    user = repo.create(email=email, password_hash=hash_password(password))
    db.flush()

    session = create_session(db, user.id)
    db.commit()
    return user.id, session.id


# ---------------------------------------------------------------------------
# 1. Password hashing
# ---------------------------------------------------------------------------


class TestPasswordHashing:
    """Password hash/verify — easy-to-get-wrong logic."""

    def test_hash_and_verify_roundtrip(self) -> None:
        """hash_password then verify_password with correct password returns True."""
        from app.auth.passwords import hash_password, verify_password

        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("correct-horse-battery-staple", hashed) is True

    def test_wrong_password_returns_false(self) -> None:
        """verify_password returns False for a wrong password (does not raise)."""
        from app.auth.passwords import hash_password, verify_password

        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_hash_is_not_plaintext(self) -> None:
        """The stored hash must not contain the plaintext password."""
        from app.auth.passwords import hash_password

        plaintext = "super-secret"
        hashed = hash_password(plaintext)
        assert plaintext not in hashed

    def test_two_hashes_of_same_password_differ(self) -> None:
        """Each call to hash_password produces a distinct hash (random salt)."""
        from app.auth.passwords import hash_password

        h1 = hash_password("same-password")
        h2 = hash_password("same-password")
        assert h1 != h2  # Different salts → different hashes.


# ---------------------------------------------------------------------------
# 2. Session create → verify roundtrip
# ---------------------------------------------------------------------------


class TestSessionCreateVerify:
    """Session roundtrip — easy-to-get-wrong logic."""

    def test_create_then_verify_returns_session(self, db_session: Session) -> None:
        """create() then verify() returns the same session."""
        from app.auth.passwords import hash_password
        from app.auth.sessions import create, verify
        from app.repositories.user import UserRepository

        repo = UserRepository(db_session)
        user = repo.create(email="user@example.com", password_hash=hash_password("pw"))
        db_session.flush()

        session = create(db_session, user.id)
        db_session.commit()

        found = verify(db_session, session.id)
        assert found is not None
        assert found.id == session.id
        assert found.user_id == user.id

    def test_verify_unknown_id_returns_none(self, db_session: Session) -> None:
        """verify() returns None for a completely unknown session id."""
        from app.auth.sessions import verify

        assert verify(db_session, "no-such-session-id") is None

    def test_create_sets_expires_at_in_future(self, db_session: Session) -> None:
        """New sessions must have expires_at in the future."""
        from app.auth.passwords import hash_password
        from app.auth.sessions import _as_utc, create
        from app.repositories.user import UserRepository

        repo = UserRepository(db_session)
        user = repo.create(email="u@example.com", password_hash=hash_password("pw"))
        db_session.flush()

        session = create(db_session, user.id)
        db_session.commit()

        # SQLite may return a naive datetime; normalise to UTC for comparison.
        assert _as_utc(session.expires_at) > datetime.now(UTC)


# ---------------------------------------------------------------------------
# 3. Expired session is rejected
# ---------------------------------------------------------------------------


class TestSessionExpiry:
    """Expired session rejection — easy-to-get-wrong logic."""

    def test_expired_session_returns_none(self, db_session: Session) -> None:
        """verify() returns None when expires_at is in the past."""
        from app.auth.passwords import hash_password
        from app.auth.sessions import create, verify
        from app.repositories.user import UserRepository

        repo = UserRepository(db_session)
        user = repo.create(email="u@example.com", password_hash=hash_password("pw"))
        db_session.flush()

        session = create(db_session, user.id)
        # Manually back-date the expiry so the session is already expired.
        session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db_session.commit()

        result = verify(db_session, session.id)
        assert result is None

    def test_expired_session_row_persists_after_verify_purged_by_purge_expired(
        self, db_session: Session
    ) -> None:
        """verify() is a pure read: it rejects expired sessions but does NOT delete the row.

        The row stays present after verify() returns None.  Actual cleanup is
        the responsibility of purge_expired(), which is called on app startup.
        This test asserts both halves of that contract honestly:
        1. verify() returns None (expired session rejected).
        2. The row is still in the DB after verify() — no hidden DELETE.
        3. purge_expired() removes the row.
        """
        from app.auth.passwords import hash_password
        from app.auth.sessions import create, purge_expired, verify
        from app.models.session import Session as SessionModel
        from app.repositories.user import UserRepository

        repo = UserRepository(db_session)
        user = repo.create(email="u2@example.com", password_hash=hash_password("pw"))
        db_session.flush()

        session = create(db_session, user.id)
        session_id = session.id
        session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db_session.commit()

        # 1. verify() must reject the expired session.
        result = verify(db_session, session_id)
        assert result is None, "verify() must return None for an expired session"

        # 2. The row must still be present — verify() is a pure read.
        #    (No commit needed; we're asserting the DB was not mutated.)
        still_there = db_session.get(SessionModel, session_id)
        assert still_there is not None, (
            "verify() must NOT delete the expired row; purge_expired() is responsible for cleanup"
        )

        # 3. purge_expired() must delete the row.
        count = purge_expired(db_session)
        db_session.commit()
        assert count >= 1, "purge_expired() must report at least one deleted row"
        assert db_session.get(SessionModel, session_id) is None, (
            "purge_expired() must remove the expired row"
        )


# ---------------------------------------------------------------------------
# 4. Logout truly revokes
# ---------------------------------------------------------------------------


class TestLogoutRevokes:
    """Logout truly revokes — easy-to-get-wrong logic."""

    def test_revoke_then_verify_returns_none(self, db_session: Session) -> None:
        """After revoke(), verify() returns None (session is deleted)."""
        from app.auth.passwords import hash_password
        from app.auth.sessions import create, revoke, verify
        from app.repositories.user import UserRepository

        repo = UserRepository(db_session)
        user = repo.create(email="u@example.com", password_hash=hash_password("pw"))
        db_session.flush()

        session = create(db_session, user.id)
        db_session.commit()

        # Verify it exists first.
        assert verify(db_session, session.id) is not None
        db_session.commit()

        revoke(db_session, session.id)
        db_session.commit()

        # After revocation, verify must return None.
        assert verify(db_session, session.id) is None

    def test_revoke_is_idempotent(self, db_session: Session) -> None:
        """Revoking a non-existent session id is a no-op (doesn't raise)."""
        from app.auth.sessions import revoke

        revoke(db_session, "ghost-session-id")  # Must not raise.
        db_session.commit()

    def test_logout_endpoint_revokes_session(self, test_client: TestClient) -> None:
        """POST /auth/logout deletes the server-side session."""
        from app.db.base import get_engine
        from app.models.session import Session as SessionModel

        # Create a user and log in.
        engine = get_engine()
        factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        db = factory()
        user_id, session_id = _create_user_and_session(db)
        db.close()

        # Set the cookie manually (ENVIRONMENT=test → no Secure flag needed).
        from app.config import get_settings

        settings = get_settings()
        test_client.cookies.set(settings.session_cookie_name, session_id)

        # Call logout.
        response = test_client.post("/api/auth/logout")
        assert response.status_code == 200

        # Verify the session row is gone.
        db2 = factory()
        assert db2.get(SessionModel, session_id) is None
        db2.close()


# ---------------------------------------------------------------------------
# 5. Cookie flags
# ---------------------------------------------------------------------------


class TestCookieFlags:
    """Cookie flags — HttpOnly, SameSite=Lax always; Secure depends on env."""

    def test_login_sets_httponly_cookie(
        self,
        test_client: TestClient,
        temp_db: Path,  # noqa: ARG002
    ) -> None:
        """Login response must include Set-Cookie with HttpOnly."""
        from app.auth.passwords import hash_password
        from app.db.base import get_engine
        from app.repositories.user import UserRepository

        engine = get_engine()
        factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        db = factory()
        repo = UserRepository(db)
        repo.create(email="cookie@example.com", password_hash=hash_password("pass123"))
        db.commit()
        db.close()

        response = test_client.post(
            "/api/auth/login",
            json={"email": "cookie@example.com", "password": "pass123"},
        )
        assert response.status_code == 200
        set_cookie = response.headers.get("set-cookie", "")
        assert "httponly" in set_cookie.lower()

    def test_login_sets_samesite_lax(self, test_client: TestClient) -> None:
        """Login response must include SameSite=Lax in the Set-Cookie header."""
        from app.auth.passwords import hash_password
        from app.db.base import get_engine
        from app.repositories.user import UserRepository

        engine = get_engine()
        factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        db = factory()
        repo = UserRepository(db)
        repo.create(email="samesite@example.com", password_hash=hash_password("pass123"))
        db.commit()
        db.close()

        response = test_client.post(
            "/api/auth/login",
            json={"email": "samesite@example.com", "password": "pass123"},
        )
        assert response.status_code == 200
        set_cookie = response.headers.get("set-cookie", "")
        assert "samesite=lax" in set_cookie.lower()

    def test_secure_flag_absent_in_test_environment(self, test_client: TestClient) -> None:
        """In test environment (ENVIRONMENT=test), Secure flag must NOT be set.

        This verifies our documented policy: Secure=False in dev/test so
        plain-HTTP flows work.
        """
        from app.auth.passwords import hash_password
        from app.db.base import get_engine
        from app.repositories.user import UserRepository

        engine = get_engine()
        factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        db = factory()
        repo = UserRepository(db)
        repo.create(email="nonsecure@example.com", password_hash=hash_password("pass123"))
        db.commit()
        db.close()

        response = test_client.post(
            "/api/auth/login",
            json={"email": "nonsecure@example.com", "password": "pass123"},
        )
        assert response.status_code == 200
        set_cookie = response.headers.get("set-cookie", "")
        # In test env, 'secure' must not appear in the cookie header.
        assert "secure" not in set_cookie.lower()

    def test_secure_flag_set_in_production_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """In production environment, Secure flag must be set on the cookie.

        This test verifies the production-path logic by directly inspecting
        ``_set_session_cookie`` with a production settings context, without
        needing an actual HTTPS connection.
        """
        from unittest.mock import MagicMock

        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("ENVIRONMENT", "production")

        from app.config import get_settings

        get_settings.cache_clear()

        from app.api.routes.auth import _set_session_cookie

        mock_response = MagicMock()
        _set_session_cookie(mock_response, "test-session-id")

        # Check that set_cookie was called with secure=True.
        call_kwargs = mock_response.set_cookie.call_args.kwargs
        assert call_kwargs.get("secure") is True
        assert call_kwargs.get("httponly") is True
        assert call_kwargs.get("samesite") == "lax"


# ---------------------------------------------------------------------------
# 6. me endpoint: 401 without / 200 with valid cookie
# ---------------------------------------------------------------------------


class TestMeEndpoint:
    """me endpoint — 401 without / 200 with cookie."""

    def test_me_without_cookie_returns_401(self, test_client: TestClient) -> None:
        """GET /auth/me without a session cookie must return 401."""
        response = test_client.get("/api/auth/me")
        assert response.status_code == 401

    def test_me_with_valid_cookie_returns_200(self, test_client: TestClient) -> None:
        """GET /auth/me with a valid session cookie must return 200 and user data."""
        from app.db.base import get_engine

        engine = get_engine()
        factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        db = factory()
        user_id, session_id = _create_user_and_session(db, email="me@example.com")
        db.close()

        from app.config import get_settings

        settings = get_settings()
        test_client.cookies.set(settings.session_cookie_name, session_id)

        response = test_client.get("/api/auth/me")
        assert response.status_code == 200
        body = response.json()
        assert "user" in body
        assert body["user"]["id"] == user_id
        assert body["user"]["email"] == "me@example.com"

    def test_me_with_invalid_cookie_returns_401(self, test_client: TestClient) -> None:
        """GET /auth/me with a non-existent session id must return 401."""
        from app.config import get_settings

        settings = get_settings()
        test_client.cookies.set(settings.session_cookie_name, "totally-fake-session-id")

        response = test_client.get("/api/auth/me")
        assert response.status_code == 401

    def test_me_with_expired_session_returns_401(self, test_client: TestClient) -> None:
        """GET /auth/me with an expired session must return 401."""
        from app.db.base import get_engine
        from app.models.session import Session as SessionModel

        engine = get_engine()
        factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        db = factory()
        _, session_id = _create_user_and_session(db, email="expired@example.com")

        # Back-date expiry.
        session = db.get(SessionModel, session_id)
        assert session is not None
        session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        db.close()

        from app.config import get_settings

        settings = get_settings()
        test_client.cookies.set(settings.session_cookie_name, session_id)

        response = test_client.get("/api/auth/me")
        assert response.status_code == 401

    def test_me_with_inactive_user_returns_401(self, test_client: TestClient) -> None:
        """GET /auth/me for an inactive user must return 401."""
        from app.db.base import get_engine
        from app.models.user import User as UserModel

        engine = get_engine()
        factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        db = factory()
        user_id, session_id = _create_user_and_session(db, email="inactive@example.com")

        # Deactivate the user.
        user = db.get(UserModel, user_id)
        assert user is not None
        user.is_active = False
        db.commit()
        db.close()

        from app.config import get_settings

        settings = get_settings()
        test_client.cookies.set(settings.session_cookie_name, session_id)

        response = test_client.get("/api/auth/me")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# 7. Login / Logout full HTTP flow
# ---------------------------------------------------------------------------


class TestLoginLogoutFlow:
    """Full login → me → logout → me HTTP flow."""

    def test_login_success(self, test_client: TestClient) -> None:
        """POST /auth/login with correct credentials returns 200 + user data."""
        from app.auth.passwords import hash_password
        from app.db.base import get_engine
        from app.repositories.user import UserRepository

        engine = get_engine()
        factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        db = factory()
        repo = UserRepository(db)
        repo.create(email="login@example.com", password_hash=hash_password("correctpass"))
        db.commit()
        db.close()

        response = test_client.post(
            "/api/auth/login",
            json={"email": "login@example.com", "password": "correctpass"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["email"] == "login@example.com"

    def test_login_wrong_password_returns_401(self, test_client: TestClient) -> None:
        """POST /auth/login with wrong password returns 401."""
        from app.auth.passwords import hash_password
        from app.db.base import get_engine
        from app.repositories.user import UserRepository

        engine = get_engine()
        factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        db = factory()
        repo = UserRepository(db)
        repo.create(email="wrongpw@example.com", password_hash=hash_password("correctpass"))
        db.commit()
        db.close()

        response = test_client.post(
            "/api/auth/login",
            json={"email": "wrongpw@example.com", "password": "wrongpassword"},
        )
        assert response.status_code == 401

    def test_login_unknown_email_returns_401(self, test_client: TestClient) -> None:
        """POST /auth/login with unknown email returns 401."""
        response = test_client.post(
            "/api/auth/login",
            json={"email": "ghost@example.com", "password": "somepass"},
        )
        assert response.status_code == 401

    def test_full_login_me_logout_me_flow(self, test_client: TestClient) -> None:
        """Full flow: login → me (200) → logout → me (401)."""
        from app.auth.passwords import hash_password
        from app.db.base import get_engine
        from app.repositories.user import UserRepository

        engine = get_engine()
        factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        db = factory()
        repo = UserRepository(db)
        repo.create(email="flow@example.com", password_hash=hash_password("flowpass"))
        db.commit()
        db.close()

        # Login — TestClient persists the Set-Cookie automatically.
        login_resp = test_client.post(
            "/api/auth/login",
            json={"email": "flow@example.com", "password": "flowpass"},
        )
        assert login_resp.status_code == 200

        # me should now return 200.
        me_resp = test_client.get("/api/auth/me")
        assert me_resp.status_code == 200
        assert me_resp.json()["user"]["email"] == "flow@example.com"

        # Logout.
        logout_resp = test_client.post("/api/auth/logout")
        assert logout_resp.status_code == 200

        # me should now return 401.
        me_after_resp = test_client.get("/api/auth/me")
        assert me_after_resp.status_code == 401


# ---------------------------------------------------------------------------
# 8. Admin bootstrap idempotency
# ---------------------------------------------------------------------------


class TestAdminBootstrap:
    """Bootstrap idempotent — easy-to-get-wrong logic."""

    def test_bootstrap_creates_admin_on_first_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_bootstrap_admin() creates exactly one admin when none exists."""
        url, db_path = _make_temp_db_url()
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv("ADMIN_BOOTSTRAP_EMAIL", "admin@example.com")
        monkeypatch.setenv("ADMIN_BOOTSTRAP_PASSWORD", "adminpass123")

        from app.db.base import Base, get_engine
        from app.main import _bootstrap_admin
        from app.repositories.user import UserRepository

        engine = get_engine()
        Base.metadata.create_all(engine)
        try:
            _bootstrap_admin()

            factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
            db = factory()
            repo = UserRepository(db)
            user = repo.get_by_email("admin@example.com")
            assert user is not None
            assert user.role == "admin"
            assert user.is_active is True
            db.close()
        finally:
            Base.metadata.drop_all(engine)
            if db_path.exists():
                db_path.unlink()

    def test_bootstrap_idempotent_running_twice_gives_one_admin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Calling _bootstrap_admin() twice must leave exactly one admin user."""
        url, db_path = _make_temp_db_url()
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv("ADMIN_BOOTSTRAP_EMAIL", "admin@example.com")
        monkeypatch.setenv("ADMIN_BOOTSTRAP_PASSWORD", "adminpass123")

        from app.db.base import Base, get_engine
        from app.main import _bootstrap_admin
        from app.repositories.user import UserRepository

        engine = get_engine()
        Base.metadata.create_all(engine)
        try:
            _bootstrap_admin()  # First call — creates admin.
            _bootstrap_admin()  # Second call — must be a no-op.

            factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
            db = factory()
            repo = UserRepository(db)
            assert repo.count() == 1, "Exactly one admin user must exist after two bootstrap calls."
            db.close()
        finally:
            Base.metadata.drop_all(engine)
            if db_path.exists():
                db_path.unlink()

    def test_bootstrap_skips_when_email_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_bootstrap_admin() is a no-op when ADMIN_BOOTSTRAP_EMAIL is unset."""
        url, db_path = _make_temp_db_url()
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.delenv("ADMIN_BOOTSTRAP_EMAIL", raising=False)
        monkeypatch.delenv("ADMIN_BOOTSTRAP_PASSWORD", raising=False)

        from app.db.base import Base, get_engine
        from app.main import _bootstrap_admin
        from app.repositories.user import UserRepository

        engine = get_engine()
        Base.metadata.create_all(engine)
        try:
            _bootstrap_admin()

            factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
            db = factory()
            repo = UserRepository(db)
            assert repo.count() == 0
            db.close()
        finally:
            Base.metadata.drop_all(engine)
            if db_path.exists():
                db_path.unlink()

    def test_bootstrap_via_lifespan_creates_admin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Admin created via lifespan startup is accessible via login."""
        url, db_path = _make_temp_db_url()
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv("ADMIN_BOOTSTRAP_EMAIL", "boot@example.com")
        monkeypatch.setenv("ADMIN_BOOTSTRAP_PASSWORD", "bootpass456")

        from app.db.base import Base, get_engine
        from app.main import create_app

        engine = get_engine()
        Base.metadata.create_all(engine)
        try:
            app = create_app()
            with TestClient(app, raise_server_exceptions=True) as client:
                response = client.post(
                    "/api/auth/login",
                    json={"email": "boot@example.com", "password": "bootpass456"},
                )
                assert response.status_code == 200
                assert response.json()["email"] == "boot@example.com"
        finally:
            Base.metadata.drop_all(engine)
            if db_path.exists():
                db_path.unlink()


# ---------------------------------------------------------------------------
# 9. Alembic migration 0002
# ---------------------------------------------------------------------------


class TestAlembicMigration0002:
    """Migration 0002 must apply clean on top of 0001 and be reversible."""

    def _run_alembic(self, *args: str, url: str) -> tuple[int, str]:
        """Run alembic as a subprocess; return (returncode, output)."""
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

    def test_upgrade_head_creates_users_and_sessions(self) -> None:
        """alembic upgrade head creates users and sessions tables."""
        url, db_path = _make_temp_db_url()
        try:
            rc, output = self._run_alembic("upgrade", "head", url=url)
            assert rc == 0, f"alembic upgrade head failed:\n{output}"

            engine = create_engine(url)
            with engine.connect() as conn:
                tables = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                ).fetchall()
                table_names = {row[0] for row in tables}
                assert "users" in table_names, f"users table missing; found: {table_names}"
                assert "sessions" in table_names, f"sessions table missing; found: {table_names}"
                assert "households" in table_names, "households table missing"
        finally:
            if db_path.exists():
                db_path.unlink()

    def test_downgrade_base_removes_all_tables(self) -> None:
        """alembic downgrade base removes users, sessions, and households tables."""
        url, db_path = _make_temp_db_url()
        try:
            rc_up, out_up = self._run_alembic("upgrade", "head", url=url)
            assert rc_up == 0, f"alembic upgrade failed:\n{out_up}"

            rc_down, out_down = self._run_alembic("downgrade", "base", url=url)
            assert rc_down == 0, f"alembic downgrade failed:\n{out_down}"

            engine = create_engine(url)
            with engine.connect() as conn:
                tables = conn.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name NOT LIKE 'alembic_%' AND name != 'sqlite_sequence'"
                    )
                ).fetchall()
                assert tables == [], f"Tables still exist after downgrade: {tables}"
        finally:
            if db_path.exists():
                db_path.unlink()

    def test_upgrade_0001_then_0002_applies_clean(self) -> None:
        """Upgrading stepwise 0001→0002 must succeed cleanly."""
        url, db_path = _make_temp_db_url()
        try:
            rc1, out1 = self._run_alembic("upgrade", "0001", url=url)
            assert rc1 == 0, f"alembic upgrade 0001 failed:\n{out1}"

            rc2, out2 = self._run_alembic("upgrade", "0002", url=url)
            assert rc2 == 0, f"alembic upgrade 0002 failed:\n{out2}"

            engine = create_engine(url)
            with engine.connect() as conn:
                tables = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                ).fetchall()
                table_names = {row[0] for row in tables}
                assert "users" in table_names
                assert "sessions" in table_names
        finally:
            if db_path.exists():
                db_path.unlink()


# ---------------------------------------------------------------------------
# 10. UserRepository
# ---------------------------------------------------------------------------


class TestUserRepository:
    """UserRepository CRUD coverage."""

    def test_create_and_get_by_email(self, db_session: Session) -> None:
        """create() persists user; get_by_email() retrieves it."""
        from app.auth.passwords import hash_password
        from app.repositories.user import UserRepository

        repo = UserRepository(db_session)
        user = repo.create(email="repo@example.com", password_hash=hash_password("pw"))
        db_session.commit()

        found = repo.get_by_email("repo@example.com")
        assert found is not None
        assert found.id == user.id

    def test_get_by_email_case_insensitive(self, db_session: Session) -> None:
        """get_by_email() must be case-insensitive."""
        from app.auth.passwords import hash_password
        from app.repositories.user import UserRepository

        repo = UserRepository(db_session)
        repo.create(email="Case@Example.COM", password_hash=hash_password("pw"))
        db_session.commit()

        assert repo.get_by_email("case@example.com") is not None
        assert repo.get_by_email("CASE@EXAMPLE.COM") is not None

    def test_get_by_id(self, db_session: Session) -> None:
        """get_by_id() returns the correct user."""
        from app.auth.passwords import hash_password
        from app.repositories.user import UserRepository

        repo = UserRepository(db_session)
        user = repo.create(email="byid@example.com", password_hash=hash_password("pw"))
        db_session.commit()

        found = repo.get_by_id(user.id)
        assert found is not None
        assert found.email == "byid@example.com"

    def test_get_by_email_returns_none_when_absent(self, db_session: Session) -> None:
        """get_by_email() returns None if no user exists with that email."""
        from app.repositories.user import UserRepository

        repo = UserRepository(db_session)
        assert repo.get_by_email("nobody@example.com") is None

    def test_count_zero_initially(self, db_session: Session) -> None:
        """count() returns 0 on an empty table."""
        from app.repositories.user import UserRepository

        repo = UserRepository(db_session)
        assert repo.count() == 0

    def test_count_increments_on_create(self, db_session: Session) -> None:
        """count() reflects the number of created users."""
        from app.auth.passwords import hash_password
        from app.repositories.user import UserRepository

        repo = UserRepository(db_session)
        repo.create(email="a@example.com", password_hash=hash_password("pw"))
        repo.create(email="b@example.com", password_hash=hash_password("pw"))
        db_session.commit()
        assert repo.count() == 2


# ---------------------------------------------------------------------------
# 11. Health endpoint still works (no auth regression)
# ---------------------------------------------------------------------------


class TestHealthNotBrokenByAuth:
    """GET /health must work without authentication after adding auth routes."""

    def test_health_returns_200_without_auth(self, test_client: TestClient) -> None:
        """/api/health must return 200 without any session cookie."""
        response = test_client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# 12. Startup hooks are safe on an un-migrated DB (N1 regression guard)
# ---------------------------------------------------------------------------


class TestStartupHooksSafeOnUnmigratedDb:
    """_purge_expired_sessions and _bootstrap_admin must not crash when the DB
    schema does not yet exist (i.e. alembic upgrade head has not been run).

    This guards against the N1 regression introduced by the first fixup, where
    the unconditional DELETE FROM sessions at startup caused
    ``no such table: sessions`` on a fresh DB.
    """

    def test_purge_expired_sessions_is_noop_when_table_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_purge_expired_sessions() must not raise on an empty (un-migrated) DB."""
        url, db_path = _make_temp_db_url()
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.setenv("DATABASE_URL", url)

        try:
            from app.main import _purge_expired_sessions

            # Must complete without raising — the sessions table does not exist.
            _purge_expired_sessions()
        finally:
            if db_path.exists():
                db_path.unlink()

    def test_bootstrap_admin_is_noop_when_table_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_bootstrap_admin() must not raise on an empty (un-migrated) DB when creds are set."""
        url, db_path = _make_temp_db_url()
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv("ADMIN_BOOTSTRAP_EMAIL", "admin@example.com")
        monkeypatch.setenv("ADMIN_BOOTSTRAP_PASSWORD", "adminpass123")

        try:
            from app.main import _bootstrap_admin

            # Must complete without raising — the users table does not exist.
            _bootstrap_admin()
        finally:
            if db_path.exists():
                db_path.unlink()

    def test_app_boots_on_unmigrated_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """create_app() / lifespan startup must not raise on a fresh empty DB.

        This directly reproduces the N1 crash scenario: a brand-new SQLite
        file with no tables, startup hooks fire, app must boot without error.
        """
        url, db_path = _make_temp_db_url()
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.setenv("DATABASE_URL", url)

        try:
            from app.main import create_app

            app = create_app()
            # TestClient entering the context manager triggers the lifespan startup.
            with TestClient(app, raise_server_exceptions=True):
                pass  # If we reach here without exception, the boot succeeded.
        finally:
            if db_path.exists():
                db_path.unlink()
