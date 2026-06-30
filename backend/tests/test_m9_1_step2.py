"""M9.1 Step 2 tests: LLMProvider seam + OpenAI-compatible implementation.

Required coverage (M9.1.md §5 + §9 Step 2):

A. Protocol types
- image_part() builds the correct OpenAI vision content-part dict
- ChatMessage accepts a plain string and a list-of-parts content
- OpenAICompatibleProvider satisfies the LLMProvider Protocol structurally

B. Error mapping (httpx mocked — no real network)
- HTTP 401 → AppError(llm.auth_failed)
- HTTP 403 → AppError(llm.auth_failed)
- httpx.ConnectError → AppError(llm.connection_failed)
- httpx.TimeoutException → AppError(llm.connection_failed)
- HTTP 404 → AppError(llm.model_unavailable)
- Non-404 body containing "model not found" → AppError(llm.model_unavailable)
- HTTP 500 → AppError(llm.provider_error)
- Missing config (no base_url / model / api_key) → AppError(llm.not_configured)

C. Happy path
- Well-formed 200 parses first-choice text + model into ChatResult
- list_models() returns IDs from data[].id

D. SSRF guard applied
- provider calls validate_outbound_url before the httpx request
- LAN IP (192.168.1.x / 10.x) is allowed
- loopback IP (127.0.0.1) raises AppError(llm.unsafe_url)
- link-local / metadata IP (169.254.169.254) raises AppError(llm.unsafe_url)

E. LLMService.is_configured()
- False when all empty (defaults)
- False when only base_url set
- False when base_url + model set (no api_key)
- True when base_url + model + api_key are all set
- Flips back to False after api_key is cleared

F. build_llm_service factory
- Returns LLMService wrapping an OpenAICompatibleProvider

All tests that exercise the provider mock httpx at the ``httpx.Client`` level
(no real network connections).
"""

from __future__ import annotations

import importlib
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
# Session helpers (mirror test_m9_1_step1.py pattern)
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


def _seed_llm_config(
    db: Session,
    *,
    base_url: str | None = "http://192.168.1.100",
    model: str | None = "gpt-4o",
    api_key: str | None = "sk-test-key",
) -> None:
    """Seed LLM config keys into the settings table."""
    from app.repositories.setting import SettingsRepository

    repo = SettingsRepository(db)
    if base_url is not None:
        repo.set("llm.base_url", base_url)
    if model is not None:
        repo.set("llm.model", model)
    if api_key is not None:
        repo.set("llm.api_key", api_key)
    db.flush()


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


# ---------------------------------------------------------------------------
# Mock httpx helpers
# ---------------------------------------------------------------------------


def _mock_httpx_client(
    *,
    status_code: int = 200,
    json_body: dict[str, Any] | None = None,
    raise_exc: Exception | None = None,
) -> Any:
    """Return a mock httpx.Client context-manager that returns a fake response.

    Parameters
    ----------
    status_code:
        HTTP status code to return (only used when raise_exc is None).
    json_body:
        JSON body dict to return.
    raise_exc:
        If set, the mock ``post`` / ``get`` call raises this exception
        instead of returning a response.
    """
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    if raise_exc is not None:
        mock_ctx.post = MagicMock(side_effect=raise_exc)
        mock_ctx.get = MagicMock(side_effect=raise_exc)
    else:
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json = MagicMock(return_value=json_body or {})

        if status_code >= 400:
            # Simulate raise_for_status raising HTTPStatusError.
            http_err = httpx.HTTPStatusError(
                f"HTTP {status_code}",
                request=MagicMock(),
                response=mock_resp,
            )
            # Attach the json() to the response so _handle_http_error can call it.
            mock_resp.raise_for_status = MagicMock(side_effect=http_err)
        else:
            mock_resp.raise_for_status = MagicMock()

        mock_ctx.post = MagicMock(return_value=mock_resp)
        mock_ctx.get = MagicMock(return_value=mock_resp)

    return mock_ctx


def _patch_client(mock_ctx: Any) -> Any:
    """Return a ``patch`` context manager that replaces ``httpx.Client``."""
    return patch("httpx.Client", return_value=mock_ctx)


# ---------------------------------------------------------------------------
# A. Protocol types
# ---------------------------------------------------------------------------


class TestProtocolTypes:
    """Type and Protocol conformance tests."""

    def test_image_part_builds_correct_dict(self) -> None:
        """image_part() returns the expected OpenAI vision content-part structure."""
        from app.services.llm.provider import image_part

        result = image_part("abc123", "image/png")

        assert result == {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,abc123"},
        }

    def test_image_part_default_media_type(self) -> None:
        """image_part() defaults to image/png when media_type is omitted."""
        from app.services.llm.provider import image_part

        result = image_part("xyz")
        assert result["image_url"]["url"].startswith("data:image/png;base64,")

    def test_image_part_custom_media_type(self) -> None:
        """image_part() respects a non-default media_type."""
        from app.services.llm.provider import image_part

        result = image_part("abc", "image/jpeg")
        assert result["image_url"]["url"] == "data:image/jpeg;base64,abc"

    def test_chat_message_string_content(self) -> None:
        """ChatMessage accepts a plain string as content."""
        from app.services.llm.provider import ChatMessage

        msg = ChatMessage(role="user", content="Hello!")
        assert msg.role == "user"
        assert msg.content == "Hello!"

    def test_chat_message_list_content(self) -> None:
        """ChatMessage accepts a list of content parts (for vision)."""
        from app.services.llm.provider import ChatMessage, image_part

        parts: list[Any] = [
            {"type": "text", "text": "What is this?"},
            image_part("base64data"),
        ]
        msg = ChatMessage(role="user", content=parts)
        assert isinstance(msg.content, list)
        assert msg.content[0]["type"] == "text"
        assert msg.content[1]["type"] == "image_url"

    def test_provider_satisfies_protocol(self, db_session: Session) -> None:
        """OpenAICompatibleProvider satisfies LLMProvider structurally (isinstance)."""
        from app.services.llm.openai import OpenAICompatibleProvider
        from app.services.llm.provider import LLMProvider

        provider = OpenAICompatibleProvider(db_session)
        assert isinstance(provider, LLMProvider)

    def test_provider_does_not_inherit_protocol(self, db_session: Session) -> None:
        """OpenAICompatibleProvider is duck-typed — it does NOT subclass LLMProvider."""
        from app.services.llm.openai import OpenAICompatibleProvider
        from app.services.llm.provider import LLMProvider

        assert LLMProvider not in OpenAICompatibleProvider.__mro__


# ---------------------------------------------------------------------------
# B. Error mapping (httpx mocked)
# ---------------------------------------------------------------------------


class TestErrorMapping:
    """Provider error mapping — all httpx calls mocked, no real network."""

    def _make_provider(self, db: Session) -> Any:
        from app.services.llm.openai import OpenAICompatibleProvider

        return OpenAICompatibleProvider(db)

    def _messages(self) -> Any:
        from app.services.llm.provider import ChatMessage

        return [ChatMessage(role="user", content="Hello")]

    def test_http_401_raises_auth_failed(self, db_session: Session) -> None:
        """HTTP 401 from the provider → AppError(llm.auth_failed)."""
        from app.core.errors import AppError, ErrorCode

        _seed_llm_config(db_session)
        provider = self._make_provider(db_session)
        mock_ctx = _mock_httpx_client(status_code=401)

        with _patch_client(mock_ctx), pytest.raises(AppError) as exc_info:
            provider.chat(self._messages(), model="gpt-4o")

        assert exc_info.value.code == ErrorCode.LLM_AUTH_FAILED

    def test_http_403_raises_auth_failed(self, db_session: Session) -> None:
        """HTTP 403 from the provider → AppError(llm.auth_failed)."""
        from app.core.errors import AppError, ErrorCode

        _seed_llm_config(db_session)
        provider = self._make_provider(db_session)
        mock_ctx = _mock_httpx_client(status_code=403)

        with _patch_client(mock_ctx), pytest.raises(AppError) as exc_info:
            provider.chat(self._messages(), model="gpt-4o")

        assert exc_info.value.code == ErrorCode.LLM_AUTH_FAILED

    def test_connect_error_raises_connection_failed(self, db_session: Session) -> None:
        """httpx.ConnectError → AppError(llm.connection_failed)."""
        from app.core.errors import AppError, ErrorCode

        _seed_llm_config(db_session)
        provider = self._make_provider(db_session)
        mock_ctx = _mock_httpx_client(raise_exc=httpx.ConnectError("refused"))

        with _patch_client(mock_ctx), pytest.raises(AppError) as exc_info:
            provider.chat(self._messages(), model="gpt-4o")

        assert exc_info.value.code == ErrorCode.LLM_CONNECTION_FAILED

    def test_timeout_raises_connection_failed(self, db_session: Session) -> None:
        """httpx.TimeoutException → AppError(llm.connection_failed)."""
        from app.core.errors import AppError, ErrorCode

        _seed_llm_config(db_session)
        provider = self._make_provider(db_session)
        mock_ctx = _mock_httpx_client(raise_exc=httpx.TimeoutException("timed out"))

        with _patch_client(mock_ctx), pytest.raises(AppError) as exc_info:
            provider.chat(self._messages(), model="gpt-4o")

        assert exc_info.value.code == ErrorCode.LLM_CONNECTION_FAILED

    def test_http_404_raises_model_unavailable(self, db_session: Session) -> None:
        """HTTP 404 → AppError(llm.model_unavailable)."""
        from app.core.errors import AppError, ErrorCode

        _seed_llm_config(db_session)
        provider = self._make_provider(db_session)
        mock_ctx = _mock_httpx_client(status_code=404)
        # Make the response body parseable as JSON for the body-check branch.
        mock_ctx.__enter__.return_value.post.return_value.json.return_value = {
            "error": {"message": "Model not found"}
        }

        with _patch_client(mock_ctx), pytest.raises(AppError) as exc_info:
            provider.chat(self._messages(), model="gpt-4o")

        assert exc_info.value.code == ErrorCode.LLM_MODEL_UNAVAILABLE

    def test_body_with_model_not_found_raises_model_unavailable(self, db_session: Session) -> None:
        """A non-404 status with 'model not found' in the body → llm.model_unavailable."""
        from app.core.errors import AppError, ErrorCode

        _seed_llm_config(db_session)
        provider = self._make_provider(db_session)

        # Some providers return 400 / 422 for unknown models.
        mock_ctx = _mock_httpx_client(status_code=400)
        # Override the response body to contain the model-not-found signal.
        mock_ctx.__enter__.return_value.post.return_value.json.return_value = {
            "error": {"message": "model not found: bad-model-id"}
        }

        with _patch_client(mock_ctx), pytest.raises(AppError) as exc_info:
            provider.chat(self._messages(), model="bad-model-id")

        assert exc_info.value.code == ErrorCode.LLM_MODEL_UNAVAILABLE

    def test_http_500_raises_provider_error(self, db_session: Session) -> None:
        """HTTP 500 → AppError(llm.provider_error)."""
        from app.core.errors import AppError, ErrorCode

        _seed_llm_config(db_session)
        provider = self._make_provider(db_session)
        mock_ctx = _mock_httpx_client(status_code=500)

        with _patch_client(mock_ctx), pytest.raises(AppError) as exc_info:
            provider.chat(self._messages(), model="gpt-4o")

        assert exc_info.value.code == ErrorCode.LLM_PROVIDER_ERROR

    def test_http_503_raises_provider_error(self, db_session: Session) -> None:
        """HTTP 503 → AppError(llm.provider_error)."""
        from app.core.errors import AppError, ErrorCode

        _seed_llm_config(db_session)
        provider = self._make_provider(db_session)
        mock_ctx = _mock_httpx_client(status_code=503)

        with _patch_client(mock_ctx), pytest.raises(AppError) as exc_info:
            provider.chat(self._messages(), model="gpt-4o")

        assert exc_info.value.code == ErrorCode.LLM_PROVIDER_ERROR

    def test_no_base_url_raises_not_configured(self, db_session: Session) -> None:
        """Missing base_url → AppError(llm.not_configured)."""
        from app.core.errors import AppError, ErrorCode

        _seed_llm_config(db_session, base_url=None, model="gpt-4o", api_key="sk-key")
        provider = self._make_provider(db_session)

        with pytest.raises(AppError) as exc_info:
            provider.chat(self._messages(), model="gpt-4o")

        assert exc_info.value.code == ErrorCode.LLM_NOT_CONFIGURED

    def test_no_model_raises_not_configured(self, db_session: Session) -> None:
        """Missing model → AppError(llm.not_configured)."""
        from app.core.errors import AppError, ErrorCode

        _seed_llm_config(db_session, base_url="http://192.168.1.100", model=None, api_key="sk-key")
        provider = self._make_provider(db_session)

        with pytest.raises(AppError) as exc_info:
            provider.chat(self._messages(), model="gpt-4o")

        assert exc_info.value.code == ErrorCode.LLM_NOT_CONFIGURED

    def test_no_api_key_raises_not_configured(self, db_session: Session) -> None:
        """Missing api_key → AppError(llm.not_configured)."""
        from app.core.errors import AppError, ErrorCode

        _seed_llm_config(db_session, base_url="http://192.168.1.100", model="gpt-4o", api_key=None)
        provider = self._make_provider(db_session)

        with pytest.raises(AppError) as exc_info:
            provider.chat(self._messages(), model="gpt-4o")

        assert exc_info.value.code == ErrorCode.LLM_NOT_CONFIGURED


# ---------------------------------------------------------------------------
# C. Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Successful requests parse correctly into result types."""

    _CHAT_RESPONSE: dict[str, Any] = {
        "id": "chatcmpl-xyz",
        "model": "gpt-4o-2024-08-06",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello from the model!"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }

    _MODELS_RESPONSE: dict[str, Any] = {
        "data": [
            {"id": "gpt-4o", "object": "model"},
            {"id": "gpt-4o-mini", "object": "model"},
        ]
    }

    def _make_provider(self, db: Session) -> Any:
        from app.services.llm.openai import OpenAICompatibleProvider

        return OpenAICompatibleProvider(db)

    def _messages(self) -> Any:
        from app.services.llm.provider import ChatMessage

        return [ChatMessage(role="user", content="Hi")]

    def test_successful_200_returns_chat_result(self, db_session: Session) -> None:
        """A well-formed 200 parses the first choice text into a ChatResult."""
        from app.services.llm.provider import ChatResult

        _seed_llm_config(db_session)
        provider = self._make_provider(db_session)
        mock_ctx = _mock_httpx_client(status_code=200, json_body=self._CHAT_RESPONSE)

        with _patch_client(mock_ctx):
            result = provider.chat(self._messages(), model="gpt-4o")

        assert isinstance(result, ChatResult)
        assert result.text == "Hello from the model!"
        assert result.model == "gpt-4o-2024-08-06"
        assert result.raw["id"] == "chatcmpl-xyz"

    def test_successful_200_with_max_tokens(self, db_session: Session) -> None:
        """max_tokens is included in the POST payload when provided."""
        _seed_llm_config(db_session)
        provider = self._make_provider(db_session)
        mock_ctx = _mock_httpx_client(status_code=200, json_body=self._CHAT_RESPONSE)

        with _patch_client(mock_ctx):
            provider.chat(self._messages(), model="gpt-4o", max_tokens=100)

        call_kwargs = mock_ctx.__enter__.return_value.post.call_args
        payload = call_kwargs[1]["json"]
        assert payload["max_tokens"] == 100

    def test_successful_200_without_max_tokens(self, db_session: Session) -> None:
        """max_tokens is omitted from the POST payload when not provided."""
        _seed_llm_config(db_session)
        provider = self._make_provider(db_session)
        mock_ctx = _mock_httpx_client(status_code=200, json_body=self._CHAT_RESPONSE)

        with _patch_client(mock_ctx):
            provider.chat(self._messages(), model="gpt-4o")

        call_kwargs = mock_ctx.__enter__.return_value.post.call_args
        payload = call_kwargs[1]["json"]
        assert "max_tokens" not in payload

    def test_temperature_included_when_provided(self, db_session: Session) -> None:
        """temperature is included in the POST payload when provided."""
        _seed_llm_config(db_session)
        provider = self._make_provider(db_session)
        mock_ctx = _mock_httpx_client(status_code=200, json_body=self._CHAT_RESPONSE)

        with _patch_client(mock_ctx):
            provider.chat(self._messages(), model="gpt-4o", temperature=0.5)

        call_kwargs = mock_ctx.__enter__.return_value.post.call_args
        payload = call_kwargs[1]["json"]
        assert payload["temperature"] == 0.5

    def test_post_url_is_v1_chat_completions(self, db_session: Session) -> None:
        """chat() POSTs to {base_url}/v1/chat/completions."""
        _seed_llm_config(db_session, base_url="http://192.168.1.100")
        provider = self._make_provider(db_session)
        mock_ctx = _mock_httpx_client(status_code=200, json_body=self._CHAT_RESPONSE)

        with _patch_client(mock_ctx):
            provider.chat(self._messages(), model="gpt-4o")

        call_kwargs = mock_ctx.__enter__.return_value.post.call_args
        url_called = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("url", "")
        assert "/v1/chat/completions" in url_called

    def test_authorization_bearer_header_sent(self, db_session: Session) -> None:
        """chat() sends Authorization: Bearer <api_key> in the request headers."""
        _seed_llm_config(db_session, api_key="sk-my-secret")
        provider = self._make_provider(db_session)
        mock_ctx = _mock_httpx_client(status_code=200, json_body=self._CHAT_RESPONSE)

        with _patch_client(mock_ctx):
            provider.chat(self._messages(), model="gpt-4o")

        call_kwargs = mock_ctx.__enter__.return_value.post.call_args
        headers = call_kwargs[1]["headers"]
        assert headers["Authorization"] == "Bearer sk-my-secret"

    def test_follow_redirects_false(self, db_session: Session) -> None:
        """httpx.Client is created with follow_redirects=False."""
        _seed_llm_config(db_session)
        provider = self._make_provider(db_session)
        mock_ctx = _mock_httpx_client(status_code=200, json_body=self._CHAT_RESPONSE)

        with patch("httpx.Client", return_value=mock_ctx) as mock_client_cls:
            provider.chat(self._messages(), model="gpt-4o")

        call_kwargs = mock_client_cls.call_args
        assert call_kwargs[1].get("follow_redirects") is False

    def test_list_models_returns_ids(self, db_session: Session) -> None:
        """list_models() returns model IDs from the /models data[].id field."""
        _seed_llm_config(db_session)
        provider = self._make_provider(db_session)
        mock_ctx = _mock_httpx_client(status_code=200, json_body=self._MODELS_RESPONSE)

        with _patch_client(mock_ctx):
            models = provider.list_models()

        assert models == ["gpt-4o", "gpt-4o-mini"]

    def test_list_models_uses_get_not_post(self, db_session: Session) -> None:
        """list_models() uses GET (not POST) for the /models endpoint."""
        _seed_llm_config(db_session)
        provider = self._make_provider(db_session)
        mock_ctx = _mock_httpx_client(status_code=200, json_body=self._MODELS_RESPONSE)

        with _patch_client(mock_ctx):
            provider.list_models()

        # GET should be called; POST should not.
        mock_ctx.__enter__.return_value.get.assert_called_once()
        mock_ctx.__enter__.return_value.post.assert_not_called()

    def test_multipart_message_sent_to_provider(self, db_session: Session) -> None:
        """A multipart ChatMessage (text + image part) is forwarded correctly."""
        from app.services.llm.provider import ChatMessage, image_part

        _seed_llm_config(db_session)
        provider = self._make_provider(db_session)
        mock_ctx = _mock_httpx_client(status_code=200, json_body=self._CHAT_RESPONSE)

        parts: list[Any] = [
            {"type": "text", "text": "What is in this image?"},
            image_part("base64data", "image/png"),
        ]
        msg = ChatMessage(role="user", content=parts)

        with _patch_client(mock_ctx):
            provider.chat([msg], model="gpt-4o")

        call_kwargs = mock_ctx.__enter__.return_value.post.call_args
        payload = call_kwargs[1]["json"]
        sent_content = payload["messages"][0]["content"]
        assert isinstance(sent_content, list)
        assert sent_content[0]["type"] == "text"
        assert sent_content[1]["type"] == "image_url"


# ---------------------------------------------------------------------------
# D. SSRF guard
# ---------------------------------------------------------------------------


class TestSSRFGuard:
    """SSRF guard is applied before any network connection."""

    def _make_provider(self, db: Session) -> Any:
        from app.services.llm.openai import OpenAICompatibleProvider

        return OpenAICompatibleProvider(db)

    def _messages(self) -> Any:
        from app.services.llm.provider import ChatMessage

        return [ChatMessage(role="user", content="Hi")]

    def test_validate_outbound_url_called_before_request(self, db_session: Session) -> None:
        """provider calls validate_outbound_url before the httpx request."""
        _seed_llm_config(db_session, base_url="http://192.168.1.100")
        provider = self._make_provider(db_session)

        call_order: list[str] = []

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(
            return_value={
                "model": "gpt-4o",
                "choices": [{"message": {"content": "ok"}}],
            }
        )
        mock_ctx.post = MagicMock(return_value=mock_resp)

        def fake_validate(url: str) -> None:
            call_order.append("validate")

        def fake_client(*args: Any, **kwargs: Any) -> Any:
            call_order.append("httpx")
            return mock_ctx

        # Patch at the source module (lazy import inside _validate_url reads it
        # from app.core.net_guard at call time, so patch the original location).
        with (
            patch("app.core.net_guard.validate_outbound_url", side_effect=fake_validate),
            patch("httpx.Client", side_effect=fake_client),
        ):
            provider.chat(self._messages(), model="gpt-4o")

        assert call_order[0] == "validate", "validate_outbound_url must be called before httpx"
        assert "httpx" in call_order

    def test_loopback_ip_raises_unsafe_url(self, db_session: Session) -> None:
        """base_url resolving to 127.0.0.1 (loopback) → AppError(llm.unsafe_url)."""
        from app.core.errors import AppError, ErrorCode

        # 127.0.0.1 is a loopback address; getaddrinfo returns it directly (no DNS).
        _seed_llm_config(db_session, base_url="http://127.0.0.1")
        provider = self._make_provider(db_session)

        # Do NOT mock httpx — the guard should fire before any network call.
        with pytest.raises(AppError) as exc_info:
            provider.chat(self._messages(), model="gpt-4o")

        assert exc_info.value.code == ErrorCode.LLM_UNSAFE_URL

    def test_metadata_ip_raises_unsafe_url(self, db_session: Session) -> None:
        """base_url resolving to 169.254.169.254 (link-local/metadata) → llm.unsafe_url."""
        from app.core.errors import AppError, ErrorCode

        # 169.254.169.254 is AWS instance metadata; link-local → blocked.
        _seed_llm_config(db_session, base_url="http://169.254.169.254")
        provider = self._make_provider(db_session)

        with pytest.raises(AppError) as exc_info:
            provider.chat(self._messages(), model="gpt-4o")

        assert exc_info.value.code == ErrorCode.LLM_UNSAFE_URL

    def test_lan_ip_is_allowed(self, db_session: Session) -> None:
        """Private LAN IP (192.168.x.x) passes the SSRF guard (httpx then handles it)."""
        from app.services.llm.provider import ChatResult

        _seed_llm_config(db_session, base_url="http://192.168.1.100")
        provider = self._make_provider(db_session)

        success_body = {
            "model": "gpt-4o",
            "choices": [{"message": {"content": "pong"}}],
        }
        mock_ctx = _mock_httpx_client(status_code=200, json_body=success_body)

        # The real SSRF guard runs here — it should NOT raise for 192.168.1.100.
        with _patch_client(mock_ctx):
            result = provider.chat(self._messages(), model="gpt-4o")

        assert isinstance(result, ChatResult)
        assert result.text == "pong"

    def test_private_10x_lan_ip_is_allowed(self, db_session: Session) -> None:
        """Private LAN IP (10.x.x.x) also passes the SSRF guard."""
        from app.services.llm.provider import ChatResult

        _seed_llm_config(db_session, base_url="http://10.0.0.1")
        provider = self._make_provider(db_session)

        success_body = {
            "model": "gpt-4o",
            "choices": [{"message": {"content": "pong"}}],
        }
        mock_ctx = _mock_httpx_client(status_code=200, json_body=success_body)

        with _patch_client(mock_ctx):
            result = provider.chat(self._messages(), model="gpt-4o")

        assert isinstance(result, ChatResult)


# ---------------------------------------------------------------------------
# E. LLMService.is_configured()
# ---------------------------------------------------------------------------


class TestIsConfigured:
    """is_configured() reflects whether all three LLM config values are set."""

    def _make_service(self, db: Session) -> Any:
        from app.services.llm.service import build_llm_service

        return build_llm_service(db)

    def test_false_when_all_empty(self, db_session: Session) -> None:
        """is_configured() returns False when no LLM config has been set."""
        svc = self._make_service(db_session)
        assert svc.is_configured() is False

    def test_false_when_only_base_url(self, db_session: Session) -> None:
        """is_configured() returns False when only base_url is set."""
        _seed_llm_config(db_session, base_url="http://192.168.1.100", model=None, api_key=None)
        svc = self._make_service(db_session)
        assert svc.is_configured() is False

    def test_false_when_base_url_and_model_only(self, db_session: Session) -> None:
        """is_configured() returns False when base_url + model are set but api_key is not."""
        _seed_llm_config(db_session, base_url="http://192.168.1.100", model="gpt-4o", api_key=None)
        svc = self._make_service(db_session)
        assert svc.is_configured() is False

    def test_true_when_all_three_set(self, db_session: Session) -> None:
        """is_configured() returns True when base_url + model + api_key are all set."""
        _seed_llm_config(
            db_session,
            base_url="http://192.168.1.100",
            model="gpt-4o",
            api_key="sk-key",
        )
        svc = self._make_service(db_session)
        assert svc.is_configured() is True

    def test_flips_to_false_after_api_key_cleared(self, db_session: Session) -> None:
        """is_configured() returns False after the api_key is cleared."""
        from app.repositories.setting import SettingsRepository

        _seed_llm_config(
            db_session,
            base_url="http://192.168.1.100",
            model="gpt-4o",
            api_key="sk-key",
        )
        svc = self._make_service(db_session)
        assert svc.is_configured() is True

        # Clear the api_key.
        repo = SettingsRepository(db_session)
        repo.set("llm.api_key", "")
        db_session.flush()

        assert svc.is_configured() is False


# ---------------------------------------------------------------------------
# F. build_llm_service factory
# ---------------------------------------------------------------------------


class TestBuildLLMService:
    """build_llm_service factory returns the right service type."""

    def test_returns_llm_service(self, db_session: Session) -> None:
        """build_llm_service(db) returns an LLMService instance."""
        from app.services.llm.service import LLMService, build_llm_service

        svc = build_llm_service(db_session)
        assert isinstance(svc, LLMService)

    def test_service_has_provider(self, db_session: Session) -> None:
        """build_llm_service wires an OpenAICompatibleProvider as the first provider."""
        from app.services.llm.openai import OpenAICompatibleProvider
        from app.services.llm.service import build_llm_service

        svc = build_llm_service(db_session)
        # The factory should wire exactly one provider for M9.1.
        assert len(svc._providers) == 1
        assert isinstance(svc._providers[0], OpenAICompatibleProvider)

    def test_is_configured_via_service(self, db_session: Session) -> None:
        """LLMService.is_configured() behaves correctly when built via the factory."""
        from app.services.llm.service import build_llm_service

        # Before config: False
        svc = build_llm_service(db_session)
        assert svc.is_configured() is False

        # After seeding: True
        _seed_llm_config(
            db_session,
            base_url="https://openrouter.ai/api",
            model="openai/gpt-4o-mini",
            api_key="or-sk-test",
        )
        assert svc.is_configured() is True
