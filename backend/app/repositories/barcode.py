"""Repository for the Barcode table (M5 Step 5).

Pure data access — no business rules here.  Business logic (global-unique code
guard, definition-existence check) lives in ``app.services.barcode``.

Public methods
--------------
BarcodeRepository
    create(definition_id, code, symbology, label)
        Insert and flush a new Barcode row.
    get(barcode_id)
        Return a Barcode by PK, or None.
    get_by_code(code)
        Return the Barcode matching ``code`` (globally unique), or None.
    list_for_definition(definition_id)
        All Barcodes for a given definition, ordered by id.
    delete(barcode)
        Delete a Barcode row.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.barcode import Barcode


class BarcodeRepository:
    """Data-access object for the barcodes table."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ---------------------------------------------------------------------- #
    # Read                                                                     #
    # ---------------------------------------------------------------------- #

    def get(self, barcode_id: int) -> Barcode | None:
        """Return a Barcode by PK, or None if not found."""
        return self._db.get(Barcode, barcode_id)

    def get_by_code(self, code: str) -> Barcode | None:
        """Return the Barcode matching ``code`` (globally unique), or None."""
        stmt = select(Barcode).where(Barcode.code == code)
        return self._db.scalars(stmt).first()

    def list_for_definition(self, definition_id: int) -> list[Barcode]:
        """Return all Barcodes for a given definition, ordered by id."""
        stmt = select(Barcode).where(Barcode.definition_id == definition_id).order_by(Barcode.id)
        return list(self._db.scalars(stmt).all())

    # ---------------------------------------------------------------------- #
    # Write                                                                    #
    # ---------------------------------------------------------------------- #

    def create(
        self,
        *,
        definition_id: int,
        code: str,
        symbology: str = "unknown",
        label: str | None = None,
    ) -> Barcode:
        """Insert a new Barcode row and flush to get its PK."""
        barcode = Barcode(
            definition_id=definition_id,
            code=code,
            symbology=symbology,
            label=label,
        )
        self._db.add(barcode)
        self._db.flush()
        return barcode

    def delete(self, barcode: Barcode) -> None:
        """Delete a Barcode row."""
        self._db.delete(barcode)
        self._db.flush()
