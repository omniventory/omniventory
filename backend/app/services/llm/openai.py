"""OpenAI-compatible LLM provider implementation (M9.1 Step 2).

``OpenAICompatibleProvider`` satisfies the ``LLMProvider`` Protocol
**structurally** (duck-typed).  It does NOT inherit from ``LLMProvider``
(mirrors how ``InternalProvider`` relates to ``ProductLookupProvider``).

Outbound discipline (mirrors ``app/notifications/channels/http.py``)
---------------------------------------------------------------------
- Per-call sync ``httpx.Client(timeout=_TIMEOUT_SECONDS, follow_redirects=False)``.
- ``Authorization: Bearer <api_key>`` header.
- ``raise_for_status()`` on the response.
- ``validate_outbound_url(base_url)`` called immediately before the request
  (lazy import, matching the pattern in the HTTP/MQTT call sites).
- Timeout constant is **60.0 s** (vs the channel's 5.0 s) to accommodate LLM
  latency.

Error mapping (exhaustive)
--------------------------
Condition                              → ``AppError`` code
--------------------------------------------------------------
Config incomplete (no base_url/model/api_key) → ``llm.not_configured``  (409)
``UnsafeUrlError`` from the SSRF guard        → ``llm.unsafe_url``       (422)
``httpx.ConnectError`` / ``httpx.TimeoutException`` → ``llm.connection_failed`` (502)
Any other ``httpx.RequestError``              → ``llm.connection_failed`` (502)
HTTP 401 or 403                               → ``llm.auth_failed``      (502)
HTTP 404 / "model not found" in body          → ``llm.model_unavailable`` (502)
Any other non-2xx status                      → ``llm.provider_error``   (502)
Well-formed 200                               → ``ChatResult``

``list_models()``
-----------------
Hits ``GET {base_url}/models`` — used by the Step 3 connectivity probe.
Applies the same URL validation, timeout, and error mapping.
Returns a list of model IDs (strings) from the ``data[].id`` field.

``base_url`` convention
------------------------
Follows the universal OpenAI-compatible convention (OpenAI SDK, OpenRouter,
LM Studio, vLLM, etc.): ``base_url`` already includes the version segment
(e.g. ``https://openrouter.ai/api/v1``, ``https://api.openai.com/v1``), and
endpoints are appended **without** another ``/v1``: ``{base_url}/chat/completions``
and ``{base_url}/models``. A trailing slash on the stored ``base_url`` is
stripped before use so it composes cleanly either way.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.services.llm.provider import ChatMessage, ChatResult

logger = logging.getLogger(__name__)

# Timeout for LLM calls (longer than the 5 s webhook timeout to accommodate
# model inference latency on large context windows).
_TIMEOUT_SECONDS = 60.0


class OpenAICompatibleProvider:
    """OpenAI Chat Completions provider over httpx.

    Reads the LLM config from ``SettingsService(db).llm_config()`` on every
    call so that config changes take effect without restarting the process.

    Parameters
    ----------
    db:
        Active SQLAlchemy session used to read settings via ``SettingsService``.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Public API (satisfies LLMProvider Protocol structurally)
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ChatResult:
        """Send a chat completion request to ``{base_url}/chat/completions``.

        ``base_url`` is expected to already include the version segment
        (e.g. ``https://openrouter.ai/api/v1``), matching the universal
        OpenAI-compatible convention — see the module docstring.

        Parameters
        ----------
        messages:
            Ordered conversation turns.
        model:
            Model identifier requested (e.g. ``"openai/gpt-4o-mini"``).
        max_tokens:
            Optional token ceiling; omitted from the payload when ``None``.
        temperature:
            Optional sampling temperature; omitted from the payload when ``None``.

        Returns
        -------
        ``ChatResult``
            Parsed first-choice text, model echo, and raw response body.

        Raises
        ------
        ``AppError``
            With an ``llm.*`` code on any failure (see module docstring).
        """
        base_url, api_key = self._require_config()

        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": msg.role, "content": msg.content} for msg in messages],
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature

        url = f"{base_url}/chat/completions"
        response_json = self._post(url, payload, api_key)

        # Parse the first choice's message content.
        try:
            text: str = response_json["choices"][0]["message"]["content"]
            echoed_model: str = response_json.get("model", model)
        except (KeyError, IndexError, TypeError) as exc:
            raise AppError(
                ErrorCode.LLM_PROVIDER_ERROR,
                status_code=502,
                message=f"Unexpected response shape from provider: {exc}",
            ) from exc

        return ChatResult(text=text, model=echoed_model, raw=response_json)

    def list_models(self) -> list[str]:
        """Return the list of model IDs from ``GET {base_url}/models``.

        Used by the Step 3 connectivity probe to verify the provider is
        reachable and the API key is accepted.

        Note: only ``base_url`` and ``api_key`` are required here — ``model``
        is not needed to hit the ``/models`` endpoint.  This allows the
        connectivity stage of the test to pass even when ``model`` is not yet
        configured (Stage 1 advisory, M9.1 Step 3).

        Returns
        -------
        list[str]
            Model IDs from the ``data[].id`` fields of the ``/models`` response.

        Raises
        ------
        ``AppError``
            With an ``llm.*`` code on any failure.
        """
        base_url, api_key = self._require_connectivity_config()
        url = f"{base_url}/models"
        response_json = self._get(url, api_key)

        try:
            data: list[dict[str, Any]] = response_json.get("data", [])
            return [item["id"] for item in data if isinstance(item, dict) and "id" in item]
        except (KeyError, TypeError) as exc:
            raise AppError(
                ErrorCode.LLM_PROVIDER_ERROR,
                status_code=502,
                message=f"Unexpected /models response shape: {exc}",
            ) from exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_config(self) -> tuple[str, str]:
        """Read and validate the LLM config; raise ``llm.not_configured`` if incomplete.

        Requires all three of ``base_url``, ``model``, and ``api_key``.
        Use ``_require_connectivity_config()`` for probes that only need the URL and key.

        Returns
        -------
        tuple[str, str]
            ``(base_url, api_key)`` — both guaranteed non-empty; ``base_url``
            has any trailing slash(es) stripped (see module docstring).

        Raises
        ------
        ``AppError(llm.not_configured)``
            When ``base_url``, ``model``, or ``api_key`` is not set.
        """
        from app.services.settings import SettingsService

        cfg = SettingsService(self._db).llm_config()
        if not cfg.base_url or not cfg.model or not cfg.api_key:
            raise AppError(ErrorCode.LLM_NOT_CONFIGURED, status_code=409)
        return cfg.base_url.rstrip("/"), cfg.api_key

    def _require_connectivity_config(self) -> tuple[str, str]:
        """Read and validate only ``base_url`` + ``api_key`` for connectivity probes.

        ``model`` is intentionally NOT checked here — hitting ``GET /models``
        only requires the endpoint and an authenticated key; the model name is
        irrelevant for that call.  This lets Stage 1 of ``test_connection()``
        pass even when no model has been configured yet.

        Returns
        -------
        tuple[str, str]
            ``(base_url, api_key)`` — both guaranteed non-empty; ``base_url``
            has any trailing slash(es) stripped (see module docstring).

        Raises
        ------
        ``AppError(llm.not_configured)``
            When ``base_url`` or ``api_key`` is not set.
        """
        from app.services.settings import SettingsService

        cfg = SettingsService(self._db).llm_config()
        if not cfg.base_url or not cfg.api_key:
            raise AppError(ErrorCode.LLM_NOT_CONFIGURED, status_code=409)
        return cfg.base_url.rstrip("/"), cfg.api_key

    def _validate_url(self, url: str) -> None:
        """Run the SSRF guard on *url*; raise ``llm.unsafe_url`` on rejection."""
        from app.core.net_guard import UnsafeUrlError, validate_outbound_url

        try:
            validate_outbound_url(url)
        except UnsafeUrlError as exc:
            raise AppError(
                ErrorCode.LLM_UNSAFE_URL,
                status_code=422,
                message=str(exc),
            ) from exc

    def _build_headers(self, api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _handle_http_error(self, exc: httpx.HTTPStatusError) -> None:
        """Map an HTTP status error to an ``AppError`` with an ``llm.*`` code."""
        status = exc.response.status_code

        if status in (401, 403):
            raise AppError(
                ErrorCode.LLM_AUTH_FAILED,
                status_code=502,
                message=f"Provider rejected the request (HTTP {status}).",
            ) from exc

        if status == 404:
            # Could also check for "model not found" in the body, but a 404
            # from the completions endpoint reliably means the model is absent.
            raise AppError(
                ErrorCode.LLM_MODEL_UNAVAILABLE,
                status_code=502,
                message=f"Model not found or not served by this provider (HTTP {status}).",
            ) from exc

        # Check for "model not found" wording in non-404 error bodies (some providers
        # return 400 or 422 with a "model not found" / "model_not_found" message).
        try:
            body = exc.response.json()
            error_msg = str(body).lower()
        except Exception:
            error_msg = ""

        if "model not found" in error_msg or "model_not_found" in error_msg:
            raise AppError(
                ErrorCode.LLM_MODEL_UNAVAILABLE,
                status_code=502,
                message=f"Model not found or not served by this provider (HTTP {status}).",
            ) from exc

        raise AppError(
            ErrorCode.LLM_PROVIDER_ERROR,
            status_code=502,
            message=f"Provider returned an unexpected error (HTTP {status}).",
        ) from exc

    def _post(self, url: str, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        """Validate the URL, POST the payload, and return the parsed JSON body."""
        # SSRF guard — must run before any network connection.
        self._validate_url(url)

        headers = self._build_headers(api_key)
        try:
            with httpx.Client(timeout=_TIMEOUT_SECONDS, follow_redirects=False) as client:
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            self._handle_http_error(exc)
            raise  # unreachable — _handle_http_error always raises AppError
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError) as exc:
            raise AppError(
                ErrorCode.LLM_CONNECTION_FAILED,
                status_code=502,
                message=f"Could not reach LLM provider: {exc}",
            ) from exc

        try:
            return dict(response.json())
        except Exception as exc:
            raise AppError(
                ErrorCode.LLM_PROVIDER_ERROR,
                status_code=502,
                message=f"Provider returned non-JSON body: {exc}",
            ) from exc

    def _get(self, url: str, api_key: str) -> dict[str, Any]:
        """Validate the URL, GET the resource, and return the parsed JSON body."""
        # SSRF guard — must run before any network connection.
        self._validate_url(url)

        headers = self._build_headers(api_key)
        try:
            with httpx.Client(timeout=_TIMEOUT_SECONDS, follow_redirects=False) as client:
                response = client.get(url, headers=headers)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            self._handle_http_error(exc)
            raise  # unreachable
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError) as exc:
            raise AppError(
                ErrorCode.LLM_CONNECTION_FAILED,
                status_code=502,
                message=f"Could not reach LLM provider: {exc}",
            ) from exc

        try:
            return dict(response.json())
        except Exception as exc:
            raise AppError(
                ErrorCode.LLM_PROVIDER_ERROR,
                status_code=502,
                message=f"Provider returned non-JSON body: {exc}",
            ) from exc
