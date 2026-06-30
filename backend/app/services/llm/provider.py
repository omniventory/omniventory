"""LLMProvider Protocol and request/result types (M9.1 Step 2).

Design (M9.1.md §4.1, roadmap §2.12)
--------------------------------------
The ``LLMProvider`` seam exists so that future LLM backends (different
OpenAI-compatible gateways, local models, etc.) can be swapped or chained
with **no change** to the callers (``LLMService``, and in M9.2, feature
services).  The concrete ``OpenAICompatibleProvider`` in ``openai.py``
satisfies this Protocol **structurally** (duck-typed) — it does NOT inherit
from ``LLMProvider`` (mirrors how ``InternalProvider`` relates to
``ProductLookupProvider``).

Contract: any concrete provider implementation MUST map all transport and
provider failures to ``AppError(llm.*)`` (see ``app/core/errors.py``).
Callers never catch ``httpx`` exceptions directly; they handle ``AppError``.

Types
-----
``ChatMessage``
    A single message in a conversation.  ``role`` is the OpenAI-style
    participant identifier (``"user"``, ``"assistant"``, ``"system"``).
    ``content`` is either a plain string (text) or a list of content-part
    dicts (to carry images alongside text for vision models).  The list form
    follows the OpenAI content-part schema:
    ``[{"type": "text", "text": "…"}, {"type": "image_url", …}]``.

``image_part(b64_data, media_type)``
    Helper that builds an OpenAI vision content-part dict from a base64
    payload.  Callers should use this rather than constructing the dict
    by hand to stay in sync with the expected schema shape.

``ChatResult``
    Returned by a successful ``chat()`` call.
    ``text``   — the first choice's message content as a plain string.
    ``model``  — the model identifier echoed back by the provider.
    ``raw``    — the deserialized JSON body for diagnostics / future use.

``LLMProvider`` (Protocol)
    A callable seam.  Any class that implements
    ``chat(messages, *, model, max_tokens=None, temperature=None) -> ChatResult``
    satisfies the Protocol.  ``runtime_checkable`` allows ``isinstance``
    checks in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Request / result types
# ---------------------------------------------------------------------------


@dataclass
class ChatMessage:
    """A single message in an LLM chat conversation.

    Parameters
    ----------
    role:
        Participant role — ``"user"``, ``"assistant"``, or ``"system"``.
    content:
        Message body.  Either a plain string (text-only) or a list of
        content-part dicts (for vision / multipart messages).

        Text-only example::

            ChatMessage(role="user", content="Hello!")

        Multipart (text + image) example::

            ChatMessage(role="user", content=[
                {"type": "text", "text": "What is in this image?"},
                image_part(b64_data, "image/png"),
            ])
    """

    role: str
    content: str | list[dict[str, Any]]


@dataclass
class ChatResult:
    """Result of a successful ``LLMProvider.chat()`` call.

    Attributes
    ----------
    text:
        The first choice's message content as a plain string.
    model:
        The model identifier returned by the provider (may differ from the
        requested model if the provider normalises it).
    raw:
        The full deserialised JSON response body.  Kept for diagnostics and
        to avoid re-serialisation in future structured-output / tool-call
        paths.
    """

    text: str
    model: str
    raw: dict[str, Any]


# ---------------------------------------------------------------------------
# Content-part helper
# ---------------------------------------------------------------------------


def image_part(b64_data: str, media_type: str = "image/png") -> dict[str, Any]:
    """Build an OpenAI vision content-part dict from a base64 payload.

    Parameters
    ----------
    b64_data:
        Raw base64-encoded image bytes (no ``data:…`` prefix — this helper
        adds it).
    media_type:
        MIME type of the image (default: ``"image/png"``).

    Returns
    -------
    dict
        An OpenAI-schema image_url content part::

            {
                "type": "image_url",
                "image_url": {"url": "data:<media_type>;base64,<b64_data>"},
            }
    """
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{media_type};base64,{b64_data}"},
    }


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for pluggable LLM provider implementations.

    Every concrete provider must implement ``chat(messages, …) -> ChatResult``.

    Contract
    --------
    Providers MUST map all transport and provider-level failures to
    ``AppError`` with an ``llm.*`` code (see ``app/core/errors.py``).
    They must never let ``httpx`` exceptions or raw HTTP status errors
    propagate to callers.

    The concrete M9.1 implementation is ``OpenAICompatibleProvider`` in
    ``app/services/llm/openai.py``.  It is **not** a subclass of this
    Protocol (duck-typed, structural conformance only), mirroring how
    ``InternalProvider`` relates to ``ProductLookupProvider``.
    """

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ChatResult:
        """Send a chat completion request and return the first choice.

        Parameters
        ----------
        messages:
            Ordered conversation history (system / user / assistant turns).
        model:
            Model identifier to request (e.g. ``"openai/gpt-4o-mini"``).
        max_tokens:
            Optional token ceiling for the completion.
        temperature:
            Optional sampling temperature (0.0–2.0).

        Returns
        -------
        ``ChatResult`` on success.

        Raises
        ------
        ``AppError``
            Always an ``AppError`` with an ``llm.*`` error code on any
            transport or provider failure (never a raw ``httpx`` exception).
        """
        ...
