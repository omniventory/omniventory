"""M9.1 Step 3 tests: staged LLM test-connection endpoint.

Required coverage (M9.1.md §5 + §9 Step 3):

A. Staged test logic (LLMService.test_connection — unit tests, provider mocked)
- All stages pass → ok=True, three pass stages.
- Connectivity failure → stages 2 & 3 skipped, ok=False.
- Connectivity fail with auth error → ok=False, auth_failed detail.
- Connectivity fail with connection error → ok=False, connection_failed detail.
- Model failure → stage 3 skipped, ok=False.
- Model not found → ok=False, model_unavailable detail.
- Multimodal passes when reply contains the fixture token (case-insensitive).
- Multimodal fails when reply omits the fixture token.
- Multimodal fails when provider rejects the image (AppError).
- Incomplete config (no base_url) → connectivity fail with llm.not_configured.
- Incomplete config (no api_key) → connectivity fail with llm.not_configured.
- base_url + api_key set but no model → stage 1 passes, stage 2 fails (not_configured).

B. Stage-1 advisory: list_models() does not require model in config
- Connectivity probe succeeds when only base_url + api_key are set (no model).

C. Fixture asset
- _FIXTURE_TOKEN is a non-empty string.
- _load_fixture_image_b64() returns a non-empty base64 string.
- The fixture image file exists and is readable.

D. HTTP endpoint (POST /settings/llm/test — always HTTP 200)
- All pass → 200 + ok=True.
- Connectivity failure → 200 + ok=False.
- Admin returns 200 in every case (full pass and each failure mode).
- viewer is blocked → 403 auth.forbidden.
- member is blocked → 403 auth.forbidden.

All provider/httpx calls are mocked — no real network connections.
"""

from __future__ import annotations

import importlib
import os
import tempfile
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session, sessionmaker

from tests.conftest import drop_all_sqlite

# ---------------------------------------------------------------------------
# Session / DB helpers (mirror test_m9_1_step1.py pattern)
# ---------------------------------------------------------------------------


def _make_in_memory_session() -> tuple[Session, Any]:
    """Create a fresh in-memory SQLite session with all models registered."""
    import app.db.base as db_base_mod
    import app.models.app_config as app_config_mod
    import app.models.audit_log as audit_log_mod
    import app.models.barcode as barcode_mod
    import app.models.category as cat_mod
    import app.models.household as hh_mod
    import app.models.item_definition as idef_mod
    import app.models.item_kind as ikind_mod
    import app.models.location as loc_mod
    import app.models.maintenance_schedule as ms_mod
    import app.models.media_file as media_file_mod
    import app.models.note as note_mod
    import app.models.notification as notif_mod
    import app.models.session as sess_mod
    import app.models.setting as setting_mod
    import app.models.stock_instance as si_mod
    import app.models.stock_movement as sm_mod
    import app.models.tag as tag_mod
    import app.models.user as user_mod
    import app.models.user_token as user_token_mod

    for mod in (
        db_base_mod,
        hh_mod,
        user_mod,
        sess_mod,
        app_config_mod,
        cat_mod,
        ikind_mod,
        idef_mod,
        loc_mod,
        si_mod,
        sm_mod,
        setting_mod,
        notif_mod,
        media_file_mod,
        tag_mod,
        note_mod,
        barcode_mod,
        user_token_mod,
        audit_log_mod,
        ms_mod,
    ):
        importlib.reload(mod)

    from app.db.base import Base as _Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @sa_event.listens_for(engine, "connect")
    def _enforce_fk(dbapi_conn: Any, _: Any) -> None:
        import sqlite3

        if isinstance(dbapi_conn, sqlite3.Connection):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    _Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = factory()
    return session, engine


def _make_temp_db_url() -> tuple[str, Any]:
    """Return (sqlite url, path) for a temp-file SQLite DB."""
    from pathlib import Path

    fd, path_str = tempfile.mkstemp(suffix=".db", prefix="omniventory_m9_1_step3_")
    os.close(fd)
    path = Path(path_str)
    path.unlink()
    return f"sqlite:///{path_str}", path


def _reload_all_models() -> None:
    """Reload model modules to pick up fresh DB engine after monkeypatch."""
    import app.db.base as db_base_mod
    import app.models.app_config as app_config_mod
    import app.models.audit_log as audit_log_mod
    import app.models.barcode as barcode_mod
    import app.models.category as cat_mod
    import app.models.household as hh_mod
    import app.models.item_definition as idef_mod
    import app.models.item_kind as ikind_mod
    import app.models.location as loc_mod
    import app.models.maintenance_schedule as ms_mod
    import app.models.media_file as media_file_mod
    import app.models.note as note_mod
    import app.models.notification as notif_mod
    import app.models.session as sess_mod
    import app.models.setting as setting_mod
    import app.models.stock_instance as si_mod
    import app.models.stock_movement as sm_mod
    import app.models.tag as tag_mod
    import app.models.user as user_mod
    import app.models.user_token as user_token_mod
    import app.repositories.maintenance_schedule as ms_repo_mod

    importlib.reload(db_base_mod)
    importlib.reload(hh_mod)
    importlib.reload(user_mod)
    importlib.reload(sess_mod)
    importlib.reload(app_config_mod)
    importlib.reload(cat_mod)
    importlib.reload(ikind_mod)
    importlib.reload(idef_mod)
    importlib.reload(loc_mod)
    importlib.reload(si_mod)
    importlib.reload(sm_mod)
    importlib.reload(setting_mod)
    importlib.reload(notif_mod)
    importlib.reload(media_file_mod)
    importlib.reload(tag_mod)
    importlib.reload(note_mod)
    importlib.reload(barcode_mod)
    importlib.reload(user_token_mod)
    importlib.reload(audit_log_mod)
    importlib.reload(ms_mod)
    importlib.reload(ms_repo_mod)


def _seed_llm_config(
    db: Session,
    *,
    base_url: str | None = "http://192.168.1.100",
    model: str | None = "gpt-4o",
    api_key: str | None = "sk-test-key",
) -> None:
    """Seed LLM config into the settings table."""
    from app.repositories.setting import SettingsRepository

    repo = SettingsRepository(db)
    if base_url is not None:
        repo.set("llm.base_url", base_url)
    if model is not None:
        repo.set("llm.model", model)
    if api_key is not None:
        repo.set("llm.api_key", api_key)
    db.flush()


def _seed_item_kinds(engine: Any) -> None:
    """Seed item kinds (required by some DB constraints)."""
    from sqlalchemy.orm import sessionmaker as SM

    from app.models.item_kind import ItemKind

    factory = SM(bind=engine, autocommit=False, autoflush=False)
    db = factory()
    try:
        for code, name in [
            ("durable", "Durable"),
            ("consumable", "Consumable"),
            ("perishable", "Perishable"),
        ]:
            db.add(ItemKind(code=code, name=name, is_system=True))
        db.commit()
    finally:
        db.close()


def _create_user_in_db(engine: Any, email: str, password: str, role: str) -> None:
    """Insert a user with the given role into the DB."""
    from sqlalchemy.orm import sessionmaker as SM

    from app.auth.passwords import hash_password
    from app.repositories.user import UserRepository

    factory = SM(bind=engine, autocommit=False, autoflush=False)
    db = factory()
    try:
        repo = UserRepository(db)
        repo.create(email=email, password_hash=hash_password(password), role=role)
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Mock helpers (mirrors test_m9_1_step2.py)
# ---------------------------------------------------------------------------


def _mock_chat_success(text: str = "OK") -> MagicMock:
    """Return a mock ChatResult with the given text."""
    from app.services.llm.provider import ChatResult

    result = MagicMock(spec=ChatResult)
    result.text = text
    result.model = "gpt-4o"
    result.raw = {}
    return result


def _make_provider_mock(
    *,
    list_models_side_effect: Any = None,
    chat_side_effects: list[Any] | None = None,
    chat_return_values: list[Any] | None = None,
) -> MagicMock:
    """Create a mock OpenAICompatibleProvider.

    Parameters
    ----------
    list_models_side_effect:
        If set, list_models() raises this exception. Otherwise returns [].
    chat_side_effects:
        Ordered list of side effects for successive chat() calls.
        None means use chat_return_values.
    chat_return_values:
        Ordered list of return values for successive chat() calls.
        Used when chat_side_effects is None.
    """
    from app.services.llm.openai import OpenAICompatibleProvider

    mock = MagicMock(spec=OpenAICompatibleProvider)

    if list_models_side_effect is not None:
        mock.list_models = MagicMock(side_effect=list_models_side_effect)
    else:
        mock.list_models = MagicMock(return_value=[])

    if chat_side_effects is not None:
        mock.chat = MagicMock(side_effect=chat_side_effects)
    elif chat_return_values is not None:
        mock.chat = MagicMock(side_effect=chat_return_values)
    else:
        mock.chat = MagicMock(return_value=_mock_chat_success())

    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_caches() -> Generator[None]:
    """Reset lru_cache before and after each test."""
    from app.config import get_settings
    from app.db.base import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.fixture()
def db_session() -> Generator[Session]:
    """Fresh in-memory SQLite session."""
    session, engine = _make_in_memory_session()

    from app.db.base import Base as _Base

    try:
        yield session
    finally:
        session.close()
    drop_all_sqlite(_Base, engine)


@pytest.fixture()
def temp_db(monkeypatch: pytest.MonkeyPatch) -> Generator[Any]:
    """Temp-file SQLite DB patched into DATABASE_URL."""
    url, db_path = _make_temp_db_url()
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-m9-1-step3")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DATABASE_URL", url)
    yield db_path
    if db_path.exists():
        db_path.unlink()


@pytest.fixture()
def http_client(temp_db: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Generator[Any]:
    """TestClient with full schema + authenticated admin session."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _reload_all_models()

    from app.config import get_settings
    from app.db.base import Base, get_engine
    from app.main import create_app

    get_settings.cache_clear()
    engine = get_engine()
    Base.metadata.create_all(engine)
    _seed_item_kinds(engine)
    application = create_app()

    with TestClient(application, raise_server_exceptions=True) as client:
        _create_user_in_db(engine, "admin@example.com", "adminpass", "admin")
        resp = client.post(
            "/api/auth/login",
            json={"email": "admin@example.com", "password": "adminpass"},
        )
        assert resp.status_code == 200, f"Admin login failed: {resp.json()}"
        yield client

    drop_all_sqlite(Base, engine)


# ---------------------------------------------------------------------------
# A. Fixture asset tests
# ---------------------------------------------------------------------------


class TestFixtureAsset:
    """The bundled fixture PNG and token constant are correctly set up."""

    def test_fixture_token_is_non_empty(self) -> None:
        """_FIXTURE_TOKEN is a non-empty string."""
        from app.services.llm.service import _FIXTURE_TOKEN

        assert isinstance(_FIXTURE_TOKEN, str)
        assert len(_FIXTURE_TOKEN) > 0

    def test_fixture_image_path_exists(self) -> None:
        """The fixture PNG file exists on disk."""
        from app.services.llm.service import _FIXTURE_IMAGE_PATH

        assert _FIXTURE_IMAGE_PATH.exists(), f"Fixture PNG not found at {_FIXTURE_IMAGE_PATH}"
        assert _FIXTURE_IMAGE_PATH.suffix == ".png"

    def test_load_fixture_image_b64_returns_non_empty_string(self) -> None:
        """_load_fixture_image_b64() returns a non-empty base64-encoded string."""
        import base64

        from app.services.llm.service import _load_fixture_image_b64

        result = _load_fixture_image_b64()
        assert isinstance(result, str)
        assert len(result) > 0
        # Must be valid base64
        decoded = base64.b64decode(result)
        # PNG magic bytes: \x89PNG
        assert decoded[:4] == b"\x89PNG", "Fixture is not a valid PNG"

    def test_fixture_image_is_small(self) -> None:
        """The fixture PNG is under 50 KB (a few KB as per the design doc)."""
        from app.services.llm.service import _FIXTURE_IMAGE_PATH

        size = _FIXTURE_IMAGE_PATH.stat().st_size
        assert size < 50_000, f"Fixture PNG is unexpectedly large: {size} bytes"


# ---------------------------------------------------------------------------
# B. Staged test logic — unit tests (provider mocked)
# ---------------------------------------------------------------------------


class TestStagedTestLogic:
    """LLMService.test_connection() staged logic — all provider calls mocked."""

    def _make_service_with_mock(self, db: Session, mock_provider: Any) -> Any:
        """Build an LLMService with the given mock provider injected."""
        from app.services.llm.service import LLMService

        return LLMService(db, [mock_provider])

    def test_all_stages_pass_returns_ok_true(self, db_session: Session) -> None:
        """When all three stages succeed, ok=True and all stages are 'pass'."""
        from app.services.llm.service import _FIXTURE_TOKEN

        _seed_llm_config(db_session)
        mock_provider = _make_provider_mock(
            chat_return_values=[
                _mock_chat_success("OK"),  # stage 2
                _mock_chat_success(_FIXTURE_TOKEN),  # stage 3 — contains the token
            ]
        )
        svc = self._make_service_with_mock(db_session, mock_provider)
        result = svc.test_connection()

        assert result.ok is True
        assert result.connectivity.status == "pass"
        assert result.model_answers.status == "pass"
        assert result.multimodal.status == "pass"

    def test_connectivity_failure_skips_remaining_stages(self, db_session: Session) -> None:
        """A connectivity failure (list_models raises) → stages 2&3 skipped, ok=False."""
        from app.core.errors import AppError, ErrorCode

        _seed_llm_config(db_session)
        mock_provider = _make_provider_mock(
            list_models_side_effect=AppError(ErrorCode.LLM_CONNECTION_FAILED, status_code=502)
        )
        svc = self._make_service_with_mock(db_session, mock_provider)
        result = svc.test_connection()

        assert result.ok is False
        assert result.connectivity.status == "fail"
        assert result.connectivity.detail == ErrorCode.LLM_CONNECTION_FAILED
        assert result.model_answers.status == "skipped"
        assert result.multimodal.status == "skipped"

    def test_connectivity_auth_failure_detail(self, db_session: Session) -> None:
        """401/403 from list_models → connectivity fail with llm.auth_failed detail."""
        from app.core.errors import AppError, ErrorCode

        _seed_llm_config(db_session)
        mock_provider = _make_provider_mock(
            list_models_side_effect=AppError(ErrorCode.LLM_AUTH_FAILED, status_code=502)
        )
        svc = self._make_service_with_mock(db_session, mock_provider)
        result = svc.test_connection()

        assert result.ok is False
        assert result.connectivity.status == "fail"
        assert result.connectivity.detail == ErrorCode.LLM_AUTH_FAILED
        assert result.model_answers.status == "skipped"

    def test_model_failure_skips_multimodal(self, db_session: Session) -> None:
        """Model failure in stage 2 → stage 3 skipped, ok=False."""
        from app.core.errors import AppError, ErrorCode

        _seed_llm_config(db_session)
        mock_provider = _make_provider_mock(
            chat_side_effects=[AppError(ErrorCode.LLM_MODEL_UNAVAILABLE, status_code=502)]
        )
        svc = self._make_service_with_mock(db_session, mock_provider)
        result = svc.test_connection()

        assert result.ok is False
        assert result.connectivity.status == "pass"
        assert result.model_answers.status == "fail"
        assert result.model_answers.detail == ErrorCode.LLM_MODEL_UNAVAILABLE
        assert result.multimodal.status == "skipped"

    def test_model_provider_error_in_stage2(self, db_session: Session) -> None:
        """A generic provider error in stage 2 → fail with llm.provider_error."""
        from app.core.errors import AppError, ErrorCode

        _seed_llm_config(db_session)
        mock_provider = _make_provider_mock(
            chat_side_effects=[AppError(ErrorCode.LLM_PROVIDER_ERROR, status_code=502)]
        )
        svc = self._make_service_with_mock(db_session, mock_provider)
        result = svc.test_connection()

        assert result.ok is False
        assert result.model_answers.status == "fail"
        assert result.model_answers.detail == ErrorCode.LLM_PROVIDER_ERROR
        assert result.multimodal.status == "skipped"

    def test_multimodal_passes_with_fixture_token(self, db_session: Session) -> None:
        """Stage 3 passes when the model's reply contains the fixture token."""
        from app.services.llm.service import _FIXTURE_TOKEN

        _seed_llm_config(db_session)
        mock_provider = _make_provider_mock(
            chat_return_values=[
                _mock_chat_success("OK"),  # stage 2
                _mock_chat_success(_FIXTURE_TOKEN),  # stage 3 — exact token
            ]
        )
        svc = self._make_service_with_mock(db_session, mock_provider)
        result = svc.test_connection()

        assert result.ok is True
        assert result.multimodal.status == "pass"

    def test_multimodal_passes_with_token_case_insensitive(self, db_session: Session) -> None:
        """Stage 3 passes when the reply contains the token in a different case."""
        from app.services.llm.service import _FIXTURE_TOKEN

        _seed_llm_config(db_session)
        mock_provider = _make_provider_mock(
            chat_return_values=[
                _mock_chat_success("OK"),
                _mock_chat_success(_FIXTURE_TOKEN.lower()),  # lowercased token
            ]
        )
        svc = self._make_service_with_mock(db_session, mock_provider)
        result = svc.test_connection()

        assert result.ok is True
        assert result.multimodal.status == "pass"

    def test_multimodal_fails_when_token_missing(self, db_session: Session) -> None:
        """Stage 3 fails when the model's reply does NOT contain the fixture token."""
        _seed_llm_config(db_session)
        mock_provider = _make_provider_mock(
            chat_return_values=[
                _mock_chat_success("OK"),  # stage 2
                _mock_chat_success("I cannot process images."),  # stage 3 — no token
            ]
        )
        svc = self._make_service_with_mock(db_session, mock_provider)
        result = svc.test_connection()

        assert result.ok is False
        assert result.connectivity.status == "pass"
        assert result.model_answers.status == "pass"
        assert result.multimodal.status == "fail"
        # detail should mention the not_multimodal code and include the reply
        assert result.multimodal.detail is not None
        assert (
            "not_multimodal" in result.multimodal.detail
            or "llm.not_multimodal" in result.multimodal.detail
        )

    def test_multimodal_fails_when_provider_rejects_image(self, db_session: Session) -> None:
        """Stage 3 fails when the provider raises an AppError for the vision call."""
        from app.core.errors import AppError, ErrorCode

        _seed_llm_config(db_session)
        mock_provider = _make_provider_mock(
            chat_side_effects=[
                _mock_chat_success("OK"),  # stage 2
                AppError(ErrorCode.LLM_PROVIDER_ERROR, status_code=502),  # stage 3
            ]
        )
        svc = self._make_service_with_mock(db_session, mock_provider)
        result = svc.test_connection()

        assert result.ok is False
        assert result.multimodal.status == "fail"
        assert result.multimodal.detail == ErrorCode.LLM_PROVIDER_ERROR

    def test_incomplete_config_no_base_url(self, db_session: Session) -> None:
        """Missing base_url → connectivity fail with llm.not_configured."""
        from app.core.errors import ErrorCode

        _seed_llm_config(db_session, base_url=None, model="gpt-4o", api_key="sk-key")
        mock_provider = _make_provider_mock()
        svc = self._make_service_with_mock(db_session, mock_provider)
        result = svc.test_connection()

        assert result.ok is False
        assert result.connectivity.status == "fail"
        assert result.connectivity.detail == ErrorCode.LLM_NOT_CONFIGURED
        assert result.model_answers.status == "skipped"
        assert result.multimodal.status == "skipped"
        # list_models must NOT have been called (we short-circuited before it)
        mock_provider.list_models.assert_not_called()

    def test_incomplete_config_no_api_key(self, db_session: Session) -> None:
        """Missing api_key → connectivity fail with llm.not_configured."""
        from app.core.errors import ErrorCode

        _seed_llm_config(db_session, base_url="http://192.168.1.100", model="gpt-4o", api_key=None)
        mock_provider = _make_provider_mock()
        svc = self._make_service_with_mock(db_session, mock_provider)
        result = svc.test_connection()

        assert result.ok is False
        assert result.connectivity.status == "fail"
        assert result.connectivity.detail == ErrorCode.LLM_NOT_CONFIGURED
        assert result.model_answers.status == "skipped"
        assert result.multimodal.status == "skipped"

    def test_base_url_api_key_set_no_model_stage1_passes(self, db_session: Session) -> None:
        """With base_url + api_key set but no model: stage 1 passes, stage 2 fails (not_configured).

        This is the core Stage-1 advisory fix: list_models() does NOT require model.
        """
        from app.core.errors import ErrorCode

        _seed_llm_config(db_session, base_url="http://192.168.1.100", model=None, api_key="sk-key")
        mock_provider = _make_provider_mock()  # list_models succeeds
        svc = self._make_service_with_mock(db_session, mock_provider)
        result = svc.test_connection()

        # Stage 1 should pass (list_models succeeded)
        assert result.connectivity.status == "pass"
        # Stage 2 should fail because model is not configured
        assert result.model_answers.status == "fail"
        assert result.model_answers.detail == ErrorCode.LLM_NOT_CONFIGURED
        # Stage 3 should be skipped
        assert result.multimodal.status == "skipped"
        assert result.ok is False

    def test_stage2_empty_reply_fails(self, db_session: Session) -> None:
        """Stage 2 fails when the model returns an empty reply."""
        _seed_llm_config(db_session)
        mock_provider = _make_provider_mock(
            chat_return_values=[
                _mock_chat_success(""),  # stage 2 — empty text
            ]
        )
        svc = self._make_service_with_mock(db_session, mock_provider)
        result = svc.test_connection()

        assert result.model_answers.status == "fail"
        assert result.multimodal.status == "skipped"
        assert result.ok is False

    def test_multimodal_null_reply_is_clean_fail_not_exception(self, db_session: Session) -> None:
        """Stage 3 vision call returning content=null yields a clean fail, not HTTP 500.

        Regression test for the None-guard fix: a provider that returns
        ChatResult.text=None (e.g. content-filtered image, tool_calls-only message)
        must NOT raise AttributeError — it must produce multimodal status='fail'
        with the llm.not_multimodal detail, and test_connection() must still return
        normally (no exception escaping), preserving the always-200 contract.
        """
        from app.core.errors import ErrorCode
        from app.services.llm.provider import ChatResult

        _seed_llm_config(db_session)

        # Stage 2 returns a valid text reply; stage 3 returns text=None (null content).
        null_vision_result = MagicMock(spec=ChatResult)
        null_vision_result.text = None
        null_vision_result.model = "gpt-4o"
        null_vision_result.raw = {}

        mock_provider = _make_provider_mock(
            chat_return_values=[
                _mock_chat_success("OK"),  # stage 2 — valid
                null_vision_result,  # stage 3 — content: null
            ]
        )
        svc = self._make_service_with_mock(db_session, mock_provider)

        # Must not raise — test_connection() always returns a result.
        result = svc.test_connection()

        assert result.ok is False
        assert result.connectivity.status == "pass"
        assert result.model_answers.status == "pass"
        assert result.multimodal.status == "fail"
        assert result.multimodal.detail is not None
        assert ErrorCode.LLM_NOT_MULTIMODAL in result.multimodal.detail

    def test_connectivity_unsafe_url_surfaces_correct_detail(self, db_session: Session) -> None:
        """validate_outbound_url rejection → connectivity fail with llm.unsafe_url detail.

        Covers the path where the SSRF guard rejects the base_url before any
        network call is made.  The Stage-1 except-AppError block passes exc.code
        verbatim, so the detail must equal ErrorCode.LLM_UNSAFE_URL.
        """
        from app.core.errors import AppError, ErrorCode

        _seed_llm_config(db_session)
        mock_provider = _make_provider_mock(
            list_models_side_effect=AppError(ErrorCode.LLM_UNSAFE_URL, status_code=422)
        )
        svc = self._make_service_with_mock(db_session, mock_provider)
        result = svc.test_connection()

        assert result.ok is False
        assert result.connectivity.status == "fail"
        assert result.connectivity.detail == ErrorCode.LLM_UNSAFE_URL
        assert result.model_answers.status == "skipped"
        assert result.multimodal.status == "skipped"


# ---------------------------------------------------------------------------
# C. Stage-1 advisory: list_models() doesn't need model in config
# ---------------------------------------------------------------------------


class TestConnectivityConfigAdvisory:
    """list_models() uses _require_connectivity_config() — no model required."""

    def test_list_models_succeeds_with_only_base_url_and_api_key(self, db_session: Session) -> None:
        """list_models() works when only base_url + api_key are set (no model).

        This verifies the advisory fix: the connectivity probe does NOT spuriously
        require model to be set.
        """
        from app.services.llm.openai import OpenAICompatibleProvider

        # Seed only base_url + api_key (no model)
        _seed_llm_config(
            db_session,
            base_url="http://192.168.1.100",
            model=None,
            api_key="sk-key",
        )
        provider = OpenAICompatibleProvider(db_session)

        models_response = {"data": [{"id": "gpt-4o"}]}
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value=models_response)
        mock_resp.raise_for_status = MagicMock()
        mock_ctx.get = MagicMock(return_value=mock_resp)

        with patch("httpx.Client", return_value=mock_ctx):
            # Must not raise — model not set but list_models() shouldn't need it.
            models = provider.list_models()

        assert "gpt-4o" in models

    def test_list_models_fails_without_base_url(self, db_session: Session) -> None:
        """list_models() still fails with llm.not_configured when base_url is missing."""
        from app.core.errors import AppError, ErrorCode
        from app.services.llm.openai import OpenAICompatibleProvider

        _seed_llm_config(db_session, base_url=None, model="gpt-4o", api_key="sk-key")
        provider = OpenAICompatibleProvider(db_session)

        with pytest.raises(AppError) as exc_info:
            provider.list_models()

        assert exc_info.value.code == ErrorCode.LLM_NOT_CONFIGURED

    def test_list_models_fails_without_api_key(self, db_session: Session) -> None:
        """list_models() fails with llm.not_configured when api_key is missing."""
        from app.core.errors import AppError, ErrorCode
        from app.services.llm.openai import OpenAICompatibleProvider

        _seed_llm_config(db_session, base_url="http://192.168.1.100", model="gpt-4o", api_key=None)
        provider = OpenAICompatibleProvider(db_session)

        with pytest.raises(AppError) as exc_info:
            provider.list_models()

        assert exc_info.value.code == ErrorCode.LLM_NOT_CONFIGURED

    def test_chat_still_requires_model_in_config(self, db_session: Session) -> None:
        """chat() still requires model in config (unchanged from Step 2)."""
        from app.core.errors import AppError, ErrorCode
        from app.services.llm.openai import OpenAICompatibleProvider
        from app.services.llm.provider import ChatMessage

        # base_url + api_key set, but no model
        _seed_llm_config(db_session, base_url="http://192.168.1.100", model=None, api_key="sk-key")
        provider = OpenAICompatibleProvider(db_session)

        with pytest.raises(AppError) as exc_info:
            provider.chat(
                [ChatMessage(role="user", content="test")],
                model="gpt-4o",
            )

        assert exc_info.value.code == ErrorCode.LLM_NOT_CONFIGURED


# ---------------------------------------------------------------------------
# D. HTTP endpoint: POST /settings/llm/test
# ---------------------------------------------------------------------------


class TestLlmTestEndpoint:
    """POST /settings/llm/test — always returns HTTP 200, admin-only."""

    def _seed_settings_via_api(
        self, client: Any, *, base_url: str, model: str, api_key: str
    ) -> None:
        """PATCH the LLM settings via the API."""
        resp = client.patch(
            "/api/settings",
            json={
                "llm": {
                    "base_url": base_url,
                    "model": model,
                    "api_key": api_key,
                }
            },
        )
        assert resp.status_code == 200, f"Failed to set LLM settings: {resp.json()}"

    def test_endpoint_always_returns_200_on_success(self, http_client: Any) -> None:
        """All stages pass → HTTP 200 + ok=True."""
        from app.services.llm.service import _FIXTURE_TOKEN

        self._seed_settings_via_api(
            http_client,
            base_url="http://192.168.1.100",
            model="gpt-4o",
            api_key="sk-test",
        )

        # Build a mock that succeeds list_models, then two chat calls.
        _models_resp = {"data": [{"id": "gpt-4o"}]}
        _chat_ok_resp = {
            "model": "gpt-4o",
            "choices": [{"message": {"content": "OK"}}],
        }
        _chat_multimodal_resp = {
            "model": "gpt-4o",
            "choices": [{"message": {"content": _FIXTURE_TOKEN}}],
        }

        call_count = {"n": 0}

        def _mock_get(*args: Any, **kwargs: Any) -> MagicMock:
            resp = MagicMock()
            resp.status_code = 200
            resp.json = MagicMock(return_value=_models_resp)
            resp.raise_for_status = MagicMock()
            return resp

        def _mock_post(*args: Any, **kwargs: Any) -> MagicMock:
            call_count["n"] += 1
            body = _chat_ok_resp if call_count["n"] == 1 else _chat_multimodal_resp
            resp = MagicMock()
            resp.status_code = 200
            resp.json = MagicMock(return_value=body)
            resp.raise_for_status = MagicMock()
            return resp

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.get = _mock_get
        mock_ctx.post = _mock_post

        with patch("httpx.Client", return_value=mock_ctx):
            resp = http_client.post("/api/settings/llm/test")

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["connectivity"]["status"] == "pass"
        assert body["model_answers"]["status"] == "pass"
        assert body["multimodal"]["status"] == "pass"

    def test_endpoint_returns_200_on_connectivity_failure(self, http_client: Any) -> None:
        """Connectivity failure → HTTP 200 (not an error), ok=False."""
        self._seed_settings_via_api(
            http_client,
            base_url="http://192.168.1.100",
            model="gpt-4o",
            api_key="sk-test",
        )

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.get = MagicMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.Client", return_value=mock_ctx):
            resp = http_client.post("/api/settings/llm/test")

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["connectivity"]["status"] == "fail"
        assert body["model_answers"]["status"] == "skipped"
        assert body["multimodal"]["status"] == "skipped"

    def test_endpoint_returns_200_on_model_failure(self, http_client: Any) -> None:
        """Model failure → HTTP 200, ok=False, multimodal skipped."""
        self._seed_settings_via_api(
            http_client,
            base_url="http://192.168.1.100",
            model="bad-model",
            api_key="sk-test",
        )

        _models_resp = {"data": [{"id": "gpt-4o"}]}

        def _mock_get(*args: Any, **kwargs: Any) -> MagicMock:
            resp = MagicMock()
            resp.status_code = 200
            resp.json = MagicMock(return_value=_models_resp)
            resp.raise_for_status = MagicMock()
            return resp

        def _mock_post(*args: Any, **kwargs: Any) -> MagicMock:
            resp = MagicMock()
            resp.status_code = 404
            resp.json = MagicMock(return_value={})
            resp.raise_for_status = MagicMock(
                side_effect=httpx.HTTPStatusError("HTTP 404", request=MagicMock(), response=resp)
            )
            return resp

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.get = _mock_get
        mock_ctx.post = _mock_post

        with patch("httpx.Client", return_value=mock_ctx):
            resp = http_client.post("/api/settings/llm/test")

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["connectivity"]["status"] == "pass"
        assert body["model_answers"]["status"] == "fail"
        assert body["multimodal"]["status"] == "skipped"

    def test_endpoint_returns_200_on_incomplete_config(self, http_client: Any) -> None:
        """Incomplete LLM config (no api_key) → HTTP 200, connectivity fail, stages skipped."""
        # PATCH to set base_url and model only (leave api_key unset / cleared)
        resp = http_client.patch(
            "/api/settings",
            json={"llm": {"base_url": "http://192.168.1.100", "model": "gpt-4o", "api_key": ""}},
        )
        assert resp.status_code == 200

        resp = http_client.post("/api/settings/llm/test")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["connectivity"]["status"] == "fail"
        assert body["model_answers"]["status"] == "skipped"
        assert body["multimodal"]["status"] == "skipped"


# ---------------------------------------------------------------------------
# E. Permission tests: viewer and member blocked from POST /settings/llm/test
# ---------------------------------------------------------------------------


class TestLlmTestPermissions:
    """viewer and member cannot call POST /settings/llm/test; admin can."""

    @pytest.fixture(autouse=True)
    def _setup(
        self,
        temp_db: Any,
        tmp_path: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> Generator[None]:
        """Build multi-role clients."""
        from fastapi.testclient import TestClient

        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        _reload_all_models()

        from app.config import get_settings
        from app.db.base import Base, get_engine
        from app.main import create_app

        get_settings.cache_clear()
        self._engine = get_engine()
        Base.metadata.create_all(self._engine)
        _seed_item_kinds(self._engine)
        self._Base = Base

        app = create_app()

        # Admin
        self._admin_tc = TestClient(app, raise_server_exceptions=True)
        self._admin_tc.__enter__()
        _create_user_in_db(self._engine, "admin@perm.test", "adminpass", "admin")
        r = self._admin_tc.post(
            "/api/auth/login", json={"email": "admin@perm.test", "password": "adminpass"}
        )
        assert r.status_code == 200

        # Viewer
        self._viewer_tc = TestClient(app, raise_server_exceptions=True)
        self._viewer_tc.__enter__()
        _create_user_in_db(self._engine, "viewer@perm.test", "viewerpass", "viewer")
        r = self._viewer_tc.post(
            "/api/auth/login", json={"email": "viewer@perm.test", "password": "viewerpass"}
        )
        assert r.status_code == 200

        # Member
        self._member_tc = TestClient(app, raise_server_exceptions=True)
        self._member_tc.__enter__()
        _create_user_in_db(self._engine, "member@perm.test", "memberpass", "member")
        r = self._member_tc.post(
            "/api/auth/login", json={"email": "member@perm.test", "password": "memberpass"}
        )
        assert r.status_code == 200

        yield

        self._admin_tc.__exit__(None, None, None)
        self._viewer_tc.__exit__(None, None, None)
        self._member_tc.__exit__(None, None, None)
        drop_all_sqlite(self._Base, self._engine)

    def _assert_forbidden(self, resp: Any) -> None:
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.json()}"
        body = resp.json()
        assert body["code"] == "auth.forbidden", f"Wrong code: {body}"

    def test_viewer_blocked_from_llm_test(self) -> None:
        """A viewer calling POST /settings/llm/test → 403 auth.forbidden."""
        self._assert_forbidden(self._viewer_tc.post("/api/settings/llm/test"))

    def test_member_blocked_from_llm_test(self) -> None:
        """A member calling POST /settings/llm/test → 403 auth.forbidden."""
        self._assert_forbidden(self._member_tc.post("/api/settings/llm/test"))

    def test_admin_permitted_for_llm_test(self) -> None:
        """An admin calling POST /settings/llm/test → HTTP 200 (diagnostic, not error)."""
        # No LLM config — endpoint returns 200 with ok=False (diagnostic)
        resp = self._admin_tc.post("/api/settings/llm/test")
        assert resp.status_code == 200
        body = resp.json()
        # Should have the expected structure
        assert "ok" in body
        assert "connectivity" in body
        assert "model_answers" in body
        assert "multimodal" in body
