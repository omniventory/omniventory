"""ProductLookupService — iterates the configured provider list (M5 Step 5 §4.4).

Design (M5.md §4.4)
--------------------
``ProductLookupService`` iterates its configured ``providers`` list and returns
the **first non-None** result.  If all providers return ``None`` (miss), it
returns ``None``.

M5 ships ``[InternalProvider]`` as the sole provider.  Future providers (Open
Food Facts, LLM vision) implement ``ProductLookupProvider`` and are appended
to the list (behind a settings toggle) with **no change** to this service or
the scan flow (roadmap §2.12).

``build_lookup_service(db)``
    Factory function: constructs a ``ProductLookupService`` with the M5
    default provider list ``[InternalProvider(db)]``.  Routes and
    ``BarcodeService`` call this factory rather than constructing the chain
    themselves, keeping the provider list in one place.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.product_lookup.provider import ProductLookupProvider, ProductLookupResult


class ProductLookupService:
    """Iterate a list of ``ProductLookupProvider`` instances and return the first hit.

    Attributes
    ----------
    _providers:
        Ordered list of providers to query.  The service returns the **first
        non-None** result; remaining providers are not called once a hit is found.
    """

    def __init__(self, providers: list[ProductLookupProvider]) -> None:
        self._providers = providers

    def lookup(self, code: str) -> ProductLookupResult | None:
        """Run the provider chain for ``code``.

        Iterates ``_providers`` in order and returns the first non-None result.
        Returns ``None`` if every provider returns ``None`` (unknown code).

        Parameters
        ----------
        code:
            Raw scanned / entered barcode value.

        Returns
        -------
        ``ProductLookupResult`` from the first matching provider, or ``None``.
        """
        for provider in self._providers:
            result = provider.lookup(code)
            if result is not None:
                return result
        return None


def build_lookup_service(db: Session) -> ProductLookupService:
    """Build the default M5 ``ProductLookupService`` for a given DB session.

    M5 provider list: ``[InternalProvider(db)]``.

    Future milestones add providers here (behind settings toggles) without
    touching the service class or the call sites.
    """
    from app.services.product_lookup.internal import InternalProvider

    return ProductLookupService([InternalProvider(db)])
