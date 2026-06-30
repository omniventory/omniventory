"""LLMService — wraps the configured LLM provider list (M9.1 Step 2 + 3).

Design (M9.1.md §4.1, §4.3, §12)
-----------------------------------
``LLMService`` is the single entry point for all LLM calls within the
application.  M9.1 ships one concrete provider (``OpenAICompatibleProvider``);
the list-of-one factory mirrors ``build_lookup_service`` in
``app/services/product_lookup/service.py`` so adding providers later is additive.

M9.2 features (receipt scanning, auto-categorize, semantic search) will call
``LLMService.chat(...)`` — never constructing httpx clients or reading the key
themselves.

Step 2 builds:
    - ``LLMService`` + ``is_configured()``
    - ``build_llm_service(db)`` factory

Step 3 adds:
    - ``test_connection() -> LlmTestResult`` (the staged diagnostic probe)
    - ``_FIXTURE_TOKEN`` / ``_load_fixture_image_b64()`` (the bundled multimodal probe asset)

Multimodal fixture
------------------
The fixture image ``test_fixture.png`` is committed as a static asset alongside
this module.  It renders the token ``OMNI42`` in large text.  The runtime code
reads the committed PNG and base64-encodes it — **no image library is called at
runtime**.  The token constant is kept here so the stage-3 check and the tests
share the same source of truth.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.services.llm.provider import ChatMessage, ChatResult, LLMProvider

if TYPE_CHECKING:
    from app.schemas.settings import LlmTestResult

# ---------------------------------------------------------------------------
# Multimodal fixture constants (Step 3)
# ---------------------------------------------------------------------------

# The short alphanumeric token encoded in the bundled fixture image.
# Stage 3 of test_connection() passes iff the model's reply contains this
# token (case-insensitive).  Keep this in sync with the PNG asset.
_FIXTURE_TOKEN: str = "OMNI42"

# Absolute path to the committed fixture PNG (alongside this module).
_FIXTURE_IMAGE_PATH: Path = Path(__file__).parent / "test_fixture.png"


def _load_fixture_image_b64() -> str:
    """Read the bundled fixture PNG and return its base64-encoded bytes.

    No image library is used at runtime — this is a plain file read followed
    by base64 encoding.  The PNG is committed to the repository as a static
    asset and is never modified at runtime.
    """
    return base64.b64encode(_FIXTURE_IMAGE_PATH.read_bytes()).decode("ascii")


class LLMService:
    """Wrap a list of ``LLMProvider`` instances and expose a unified chat interface.

    Currently holds a single provider (``OpenAICompatibleProvider``).  The
    list-of-one shape mirrors ``ProductLookupService`` so M9.2 can add
    providers additively.

    Parameters
    ----------
    db:
        Active SQLAlchemy session passed through to each provider.
    providers:
        Ordered list of providers.  ``chat()`` delegates to the first entry
        (list-of-one for M9.1; a chain / fallback could be wired here later).
    """

    def __init__(self, db: Session, providers: list[LLMProvider]) -> None:
        self._db = db
        self._providers = providers

    def is_configured(self) -> bool:
        """Return ``True`` iff ``base_url``, ``api_key``, and ``model`` are all set.

        This is the gate used by M9.2 features to decide whether to offer
        LLM-backed capabilities, and by the FE to show/hide the LLM section
        controls.

        Returns
        -------
        bool
            ``True`` when all three required config values are non-empty.
        """
        from app.services.settings import SettingsService

        cfg = SettingsService(self._db).llm_config()
        return bool(cfg.base_url and cfg.api_key and cfg.model)

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ChatResult:
        """Delegate to the first provider in the list.

        Parameters
        ----------
        messages:
            Ordered conversation turns.
        model:
            Model identifier to request.
        max_tokens:
            Optional token ceiling.
        temperature:
            Optional sampling temperature.

        Returns
        -------
        ``ChatResult`` from the provider.

        Raises
        ------
        ``AppError``
            Propagated from the provider with an ``llm.*`` code.
        RuntimeError
            When the provider list is empty (should not happen with the factory).
        """
        if not self._providers:
            raise RuntimeError("LLMService has no configured providers.")
        # M9.1: list-of-one; M9.2 may iterate / chain if needed.
        return self._providers[0].chat(
            messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def test_connection(self) -> LlmTestResult:
        """Run the staged LLM provider connection test (M9.1.md §4.3).

        Three stages that short-circuit — each later stage is ``skipped``
        when an earlier one fails:

        1. **connectivity** — ``GET {base_url}/models`` via
           ``list_models()``.  Requires only ``base_url`` + ``api_key``
           (model is not needed for this probe).  ``200`` → ``pass``;
           ``401/403`` → ``fail``; connection/timeout/SSRF → ``fail``;
           incomplete config → ``fail`` with ``llm.not_configured``.

        2. **model_answers** — only if stage 1 passed, else ``skipped``.
           A minimal chat round-trip on the configured model
           (``"Reply with the single word: OK"``, ``max_tokens=10``).
           Non-empty reply → ``pass``; ``llm.model_unavailable`` → ``fail``;
           other → ``fail`` with ``llm.provider_error``.

        3. **multimodal** — only if stage 2 passed, else ``skipped``.
           A chat call carrying the bundled fixture image plus the text prompt
           "What code is shown in this image? Reply with only the code.".
           The stage **passes iff** the reply contains ``_FIXTURE_TOKEN``
           (case-insensitive); otherwise ``fail`` with ``llm.not_multimodal``
           and the model's raw reply in ``detail`` so the admin can judge.

        The method **ignores the ``llm.enabled`` flag** — verification should
        work before enabling.

        Returns
        -------
        ``LlmTestResult``
            Always returns a result (never raises).  The caller's endpoint
            returns HTTP 200 regardless of the diagnostic outcome.
        """
        from app.core.errors import AppError, ErrorCode
        from app.schemas.settings import LlmTestResult, LlmTestStage
        from app.services.llm.openai import OpenAICompatibleProvider
        from app.services.llm.provider import image_part
        from app.services.settings import SettingsService

        _skipped = LlmTestStage(status="skipped", detail=None)

        # Read config once (ignores enabled flag per design).
        cfg = SettingsService(self._db).llm_config()

        # ------------------------------------------------------------------
        # Stage 1: connectivity — GET {base_url}/models
        # Requires base_url + api_key; model is NOT checked here.
        # ------------------------------------------------------------------
        if not cfg.base_url or not cfg.api_key:
            return LlmTestResult(
                ok=False,
                connectivity=LlmTestStage(
                    status="fail",
                    detail=ErrorCode.LLM_NOT_CONFIGURED,
                ),
                model_answers=_skipped,
                multimodal=_skipped,
            )

        # M9.1 list-of-one: the provider is always an OpenAICompatibleProvider.
        if not self._providers or not isinstance(self._providers[0], OpenAICompatibleProvider):
            raise RuntimeError(
                "test_connection() requires an OpenAICompatibleProvider as providers[0]."
            )
        provider: OpenAICompatibleProvider = self._providers[0]

        try:
            provider.list_models()
            connectivity = LlmTestStage(status="pass", detail=None)
        except AppError as exc:
            return LlmTestResult(
                ok=False,
                connectivity=LlmTestStage(status="fail", detail=exc.code),
                model_answers=_skipped,
                multimodal=_skipped,
            )

        # ------------------------------------------------------------------
        # Stage 2: model_answers — minimal chat round-trip
        # Requires model in addition to base_url + api_key.
        # ------------------------------------------------------------------
        if not cfg.model:
            return LlmTestResult(
                ok=False,
                connectivity=connectivity,
                model_answers=LlmTestStage(
                    status="fail",
                    detail=ErrorCode.LLM_NOT_CONFIGURED,
                ),
                multimodal=_skipped,
            )

        try:
            result = provider.chat(
                [ChatMessage(role="user", content="Reply with the single word: OK")],
                model=cfg.model,
                max_tokens=10,
            )
            if result.text and result.text.strip():
                model_answers = LlmTestStage(status="pass", detail=None)
            else:
                model_answers = LlmTestStage(
                    status="fail",
                    detail=ErrorCode.LLM_PROVIDER_ERROR,
                )
        except AppError as exc:
            detail = (
                exc.code
                if exc.code == ErrorCode.LLM_MODEL_UNAVAILABLE
                else ErrorCode.LLM_PROVIDER_ERROR
            )
            return LlmTestResult(
                ok=False,
                connectivity=connectivity,
                model_answers=LlmTestStage(status="fail", detail=detail),
                multimodal=_skipped,
            )

        if model_answers.status != "pass":
            return LlmTestResult(
                ok=False,
                connectivity=connectivity,
                model_answers=model_answers,
                multimodal=_skipped,
            )

        # ------------------------------------------------------------------
        # Stage 3: multimodal — send bundled fixture image and check token
        # ------------------------------------------------------------------
        try:
            b64_data = _load_fixture_image_b64()
            vision_message = ChatMessage(
                role="user",
                content=[
                    {
                        "type": "text",
                        "text": "What code is shown in this image? Reply with only the code.",
                    },
                    image_part(b64_data),
                ],
            )
            vision_result = provider.chat([vision_message], model=cfg.model, max_tokens=20)

            # Guard against None reply (e.g. content-filtered response from provider).
            # Mirrors Stage 2's `if result.text and result.text.strip()` guard.
            reply = vision_result.text or ""
            if _FIXTURE_TOKEN.lower() in reply.lower():
                multimodal = LlmTestStage(status="pass", detail=None)
            else:
                # Token not found — model may be text-only or misread the image.
                # Include the model's reply in detail so the admin can judge.
                multimodal = LlmTestStage(
                    status="fail",
                    detail=f"{ErrorCode.LLM_NOT_MULTIMODAL}: {reply!r}",
                )
        except AppError as exc:
            multimodal = LlmTestStage(status="fail", detail=exc.code)

        ok = (
            connectivity.status == "pass"
            and model_answers.status == "pass"
            and multimodal.status == "pass"
        )
        return LlmTestResult(
            ok=ok,
            connectivity=connectivity,
            model_answers=model_answers,
            multimodal=multimodal,
        )


def build_llm_service(db: Session) -> LLMService:
    """Build the default M9.1 ``LLMService`` for a given DB session.

    M9.1 provider list: ``[OpenAICompatibleProvider(db)]``.

    Future milestones (M9.2) add providers here (behind settings toggles)
    without touching the service class or the call sites — same shape as
    ``build_lookup_service`` in ``app/services/product_lookup/service.py``.
    """
    from app.services.llm.openai import OpenAICompatibleProvider

    return LLMService(db, [OpenAICompatibleProvider(db)])
