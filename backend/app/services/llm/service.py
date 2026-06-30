"""LLMService — wraps the configured LLM provider list (M9.1 Step 2).

Design (M9.1.md §4.1, §12)
----------------------------
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

Step 3 adds ``test_connection() -> LlmTestResult`` (the staged diagnostic).
Do NOT add it here.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.llm.provider import ChatMessage, ChatResult, LLMProvider


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


def build_llm_service(db: Session) -> LLMService:
    """Build the default M9.1 ``LLMService`` for a given DB session.

    M9.1 provider list: ``[OpenAICompatibleProvider(db)]``.

    Future milestones (M9.2) add providers here (behind settings toggles)
    without touching the service class or the call sites — same shape as
    ``build_lookup_service`` in ``app/services/product_lookup/service.py``.
    """
    from app.services.llm.openai import OpenAICompatibleProvider

    return LLMService(db, [OpenAICompatibleProvider(db)])
