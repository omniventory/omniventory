"""BarcodeService — barcode lifecycle and product lookup (M5 Step 5 §4.1).

Responsibilities
----------------
- ``bind(definition_id, code, symbology, label)``
      Validate the definition exists (404 ``item_definition.not_found``) and
      the code is globally unique (whether bound to the **same** or another
      definition → 409 ``barcode.duplicate``); then create the Barcode row.
- ``unbind(barcode_id)``
      Delete a Barcode row.  Raises 404 ``barcode.not_found`` if missing.
- ``list_for_definition(definition_id)``
      Return all Barcode rows for a definition (ordered by id).
- ``lookup(code)``
      Delegate to ``ProductLookupService`` (the M5 provider chain) and return
      the result (or ``None`` for an unknown code).

All DB access goes through ``BarcodeRepository`` and ``ItemDefinitionRepository``;
no raw queries in this layer.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.barcode import Barcode
from app.repositories.barcode import BarcodeRepository
from app.repositories.item_definition import ItemDefinitionRepository
from app.services.product_lookup.provider import ProductLookupResult
from app.services.product_lookup.service import build_lookup_service


class BarcodeService:
    """Business-logic facade for Barcode operations."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = BarcodeRepository(db)
        self._defn_repo = ItemDefinitionRepository(db)
        self._lookup_service = build_lookup_service(db)

    # ---------------------------------------------------------------------- #
    # Private helpers                                                          #
    # ---------------------------------------------------------------------- #

    def _get_or_404(self, barcode_id: int) -> Barcode:
        """Return a Barcode or raise 404 (barcode.not_found)."""
        barcode = self._repo.get(barcode_id)
        if barcode is None:
            raise AppError(
                ErrorCode.BARCODE_NOT_FOUND,
                status_code=404,
                params={"id": barcode_id},
                message=f"Barcode {barcode_id} not found.",
            )
        return barcode

    def _assert_definition_exists(self, definition_id: int) -> None:
        """Raise 404 (item_definition.not_found) if the definition does not exist."""
        if self._defn_repo.get(definition_id) is None:
            raise AppError(
                ErrorCode.ITEM_DEFINITION_NOT_FOUND,
                status_code=404,
                params={"id": definition_id},
                message=f"Item definition {definition_id} not found.",
            )

    def _assert_code_unique(self, code: str) -> None:
        """Raise 409 (barcode.duplicate) if ``code`` is already bound.

        The duplicate check is **global**: the same code bound to the same
        definition OR to any other definition is a 409.  One code → one
        definition is the invariant (M5.md §2 §4.4).
        """
        existing = self._repo.get_by_code(code)
        if existing is not None:
            raise AppError(
                ErrorCode.BARCODE_DUPLICATE,
                status_code=409,
                params={"code": code, "bound_to_definition_id": existing.definition_id},
                message=(f"Code {code!r} is already bound to definition {existing.definition_id}."),
            )

    # ---------------------------------------------------------------------- #
    # Barcode operations                                                       #
    # ---------------------------------------------------------------------- #

    def bind(
        self,
        definition_id: int,
        *,
        code: str,
        symbology: str = "unknown",
        label: str | None = None,
    ) -> Barcode:
        """Bind a code to a definition.

        Raises
        ------
        AppError(item_definition.not_found, 404)
            When the definition does not exist.
        AppError(barcode.duplicate, 409)
            When ``code`` is already bound to any definition (same or different).
        """
        self._assert_definition_exists(definition_id)
        self._assert_code_unique(code)
        return self._repo.create(
            definition_id=definition_id,
            code=code,
            symbology=symbology,
            label=label,
        )

    def unbind(self, barcode_id: int) -> None:
        """Remove a barcode binding.

        Raises
        ------
        AppError(barcode.not_found, 404)
            When the barcode does not exist.
        """
        barcode = self._get_or_404(barcode_id)
        self._repo.delete(barcode)

    def list_for_definition(self, definition_id: int) -> list[Barcode]:
        """Return all Barcodes for a definition, ordered by id."""
        return self._repo.list_for_definition(definition_id)

    # ---------------------------------------------------------------------- #
    # Product lookup                                                           #
    # ---------------------------------------------------------------------- #

    def lookup(self, code: str) -> ProductLookupResult | None:
        """Run the product-lookup provider chain for ``code``.

        Delegates to ``ProductLookupService`` (M5: ``[InternalProvider]``).

        Returns
        -------
        ``ProductLookupResult`` on a hit, ``None`` for an unknown code.
        """
        return self._lookup_service.lookup(code)
