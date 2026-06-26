"""InternalProvider — M5 built-in product-lookup provider (M5 Step 5 §4.4).

The ``InternalProvider`` implements the ``ProductLookupProvider`` Protocol by
querying the ``barcodes`` table.  If the code is bound to a definition, it
returns a ``ProductLookupResult`` with ``source="internal"`` and a
``DefinitionSummary``; otherwise it returns ``None``.

This is the **only** provider shipped in M5.  Future providers (Open Food Facts,
LLM vision — M9) implement the same Protocol and are appended to the
``ProductLookupService`` provider list without any change to this file.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.repositories.barcode import BarcodeRepository
from app.repositories.item_definition import ItemDefinitionRepository
from app.services.product_lookup.provider import (
    DefinitionSummary,
    ProductLookupResult,
)

logger = logging.getLogger(__name__)


class InternalProvider:
    """Resolve a scanned code against the local ``barcodes`` table.

    On a hit → returns ``ProductLookupResult(source="internal", definition=...)``.
    On a miss → returns ``None``.

    ``draft`` is always ``None`` (M5): the internal provider only matches codes
    that are already bound to a known definition; there is no "draft / hint"
    path for the fast-create flow until an external provider is wired in.

    Errors are caught and logged rather than raised, so the caller's provider
    chain can continue to the next provider if one exists.
    """

    def __init__(self, db: Session) -> None:
        self._barcode_repo = BarcodeRepository(db)
        self._defn_repo = ItemDefinitionRepository(db)

    def lookup(self, code: str) -> ProductLookupResult | None:
        """Look up ``code`` in the barcodes table.

        Returns
        -------
        ``ProductLookupResult`` with ``source="internal"`` and a
        ``DefinitionSummary`` on a hit, ``None`` on a miss.
        """
        try:
            barcode = self._barcode_repo.get_by_code(code)
            if barcode is None:
                return None

            defn = self._defn_repo.get(barcode.definition_id)
            if defn is None:
                # Stale barcode row (definition deleted without cascade somehow).
                logger.warning(
                    "InternalProvider: barcode %d references missing definition %d; skipping.",
                    barcode.id,
                    barcode.definition_id,
                )
                return None

            return ProductLookupResult(
                source="internal",
                definition=DefinitionSummary(id=defn.id, name=defn.name),
                draft=None,
            )
        except Exception:
            logger.exception(
                "InternalProvider.lookup raised an unexpected error for code %r.", code
            )
            return None
