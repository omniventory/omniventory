"""Product-lookup provider seam (M5 Step 5).

This package provides the ``ProductLookupProvider`` Protocol, the
``ProductLookupResult`` / ``DefinitionSummary`` data classes, the M5
``InternalProvider`` (resolves a barcode code to the bound definition), and
the ``ProductLookupService`` that iterates a configured list of providers and
returns the first non-None hit.

M5 ships **only** the ``InternalProvider``.  Future providers (Open Food Facts,
LLM vision — M9) implement the same ``ProductLookupProvider`` Protocol and are
appended to the provider list behind a settings toggle; the scan flow and
frontend don't change (roadmap §2.12).

Public surface
--------------
    DefinitionSummary       Lightweight definition id + name (for lookup response).
    ProductLookupResult     Result returned by a provider.
    ProductLookupProvider   typing.Protocol for provider implementations.
    InternalProvider        M5 internal provider (barcode table lookup).
    ProductLookupService    Iterates providers; returns first hit.
    build_lookup_service    Factory: returns a ready-to-use service for a DB session.
"""

from app.services.product_lookup.internal import InternalProvider
from app.services.product_lookup.provider import (
    DefinitionSummary,
    ProductLookupProvider,
    ProductLookupResult,
)
from app.services.product_lookup.service import ProductLookupService, build_lookup_service

__all__ = [
    "DefinitionSummary",
    "ProductLookupProvider",
    "ProductLookupResult",
    "InternalProvider",
    "ProductLookupService",
    "build_lookup_service",
]
