"""ProductLookupProvider Protocol and result types (M5 Step 5).

Design (M5.md §4.4, roadmap §2.12)
------------------------------------
The provider seam exists so that future product-lookup backends (Open Food
Facts, ISBN databases, LLM vision — M9) can be added as new provider classes
and appended to the configured list, with **no** change to the scan flow or
the frontend.  M5 ships only the ``InternalProvider``; the seam is a real
``typing.Protocol`` (not just a base class or hard-wired call).

``ProductLookupResult``
    Returned by a provider on a hit.  Fields:

    source (str)
        Machine-readable identifier for the provider that produced the result.
        M5 value: ``"internal"``.

    definition (DefinitionSummary | None)
        Lightweight summary of the matched item definition.  Present when the
        code is already bound in the ``barcodes`` table (``InternalProvider``).
        None for providers that return draft/hint data without a DB match (M9).

    draft (dict | None)
        Optional free-form draft data (name/brand/category hints) for the
        "unknown code" fast-create path.  Always ``None`` for M5's
        ``InternalProvider`` (which only matches known codes).  Reserved for
        M9 external providers.

``ProductLookupProvider`` (Protocol)
    A callable lookup seam.  Any class that implements
    ``lookup(code: str) -> ProductLookupResult | None`` satisfies the Protocol.
    ``runtime_checkable`` lets ``isinstance`` checks work in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class DefinitionSummary:
    """Lightweight representation of an item definition in a lookup response.

    Carried inside ``ProductLookupResult.definition`` and serialised to the
    ``BarcodeLookupResponse.definition`` field in the API response.
    """

    id: int
    name: str


@dataclass
class ProductLookupResult:
    """Result returned by a ``ProductLookupProvider`` on a successful hit.

    A provider returns ``None`` for a miss; it returns a ``ProductLookupResult``
    (with at least ``source`` set) for a hit.

    Attributes
    ----------
    source:
        Machine-readable provider identifier.  ``"internal"`` for the built-in
        barcode-table provider.  Future providers use distinct string identifiers
        (e.g. ``"open_food_facts"``, ``"llm_vision"``).
    definition:
        Lightweight definition summary when the code is already bound in the
        ``barcodes`` table.  ``None`` when the provider returns only draft hints
        (future M9 providers).
    draft:
        Free-form draft data (name/brand/category hints) for the "unknown code"
        fast-create path.  ``None`` for the M5 ``InternalProvider``.
    """

    source: str
    definition: DefinitionSummary | None = None
    draft: dict[str, Any] | None = field(default=None)


@runtime_checkable
class ProductLookupProvider(Protocol):
    """Protocol for pluggable product-lookup provider implementations.

    Every provider must implement ``lookup(code) -> ProductLookupResult | None``.
    Return ``None`` for a miss; return a ``ProductLookupResult`` for a hit.
    Providers must never raise — catch + log internally and return ``None`` on
    error so the chain can continue to the next provider.

    M5 ships one concrete implementation: ``InternalProvider``.  Future providers
    (Open Food Facts, LLM vision) implement the same interface and are appended
    to the ``ProductLookupService`` provider list without touching the scan flow.
    """

    def lookup(self, code: str) -> ProductLookupResult | None:
        """Look up a scanned code.

        Parameters
        ----------
        code:
            The raw decoded value from the barcode scanner (e.g. ``"5901234123457"``
            for an EAN-13, or a UUID string for an internal QR code).

        Returns
        -------
        ``ProductLookupResult`` on a hit, ``None`` on a miss.
        """
        ...
