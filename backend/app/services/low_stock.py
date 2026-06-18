"""Low-stock computed scan service (M2 §4.5).

``LowStockService`` is a pure-read service — it never writes to the DB.
It iterates over all item definitions and applies the per-mode low-stock
rule to produce the ``LowStockItem`` list consumed by ``GET /low-stock``.

Low-stock rules (M2 §3.4 / §4.5 / §12):
    exact  — SUM(lot quantities) < min_stock (strictly below; §12 notes the
              ``<`` boundary explicitly).  Only flagged when ``min_stock`` is
              not NULL.
    level  — any lot for the definition has ``stock_level == 'low'``.
    none   — never flagged.

``Decimal`` is used throughout for ``current`` and ``threshold``; never float
(roadmap §2.9).

All DB access goes through repositories; no raw queries in this layer.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.repositories.item_definition import ItemDefinitionRepository
from app.repositories.stock_instance import StockInstanceRepository
from app.schemas.low_stock import LowStockItem


class LowStockService:
    """Pure-read service that computes the current low-stock list.

    Instantiate with a DB session; call ``compute()`` to get the result.
    No writes, no persistence — the result is computed on every request.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._def_repo = ItemDefinitionRepository(db)
        self._inst_repo = StockInstanceRepository(db)

    def compute(self) -> list[LowStockItem]:
        """Return the list of definitions currently below their low-stock threshold.

        Implements M2 §4.5 exactly:

            for def in all definitions:
                if def.mode == 'exact' and def.min_stock is not None:
                    total = SUM(lot quantities)
                    if total < def.min_stock:          # strictly below (§12)
                        yield LowStockItem(...)
                elif def.mode == 'level':
                    if any lot.stock_level == 'low':
                        yield LowStockItem(...)
                # mode == 'none' → skip entirely

        Pure read — does NOT write to the DB.
        """
        results: list[LowStockItem] = []

        all_defs = self._def_repo.list_all()

        for defn in all_defs:
            mode = defn.stock_tracking_mode

            if mode == "exact" and defn.min_stock is not None:
                total = self._inst_repo.sum_quantity_for_definition(defn.id)
                if total < defn.min_stock:  # strictly below — §12: < not ≤
                    results.append(
                        LowStockItem(
                            definition_id=defn.id,
                            name=defn.name,
                            mode="exact",
                            reason="below_min_stock",
                            current=total,
                            threshold=defn.min_stock,
                        )
                    )

            elif mode == "level":
                if self._inst_repo.definition_has_low_level_lot(defn.id):
                    results.append(
                        LowStockItem(
                            definition_id=defn.id,
                            name=defn.name,
                            mode="level",
                            reason="level_low",
                            current=None,
                            threshold=None,
                        )
                    )

            # mode == 'none' → skip entirely

        return results
