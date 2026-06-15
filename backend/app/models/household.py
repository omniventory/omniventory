"""SQLAlchemy model for the Household singleton.

Design — two-layer singleton invariant
---------------------------------------
This deployment is single-tenant: exactly **one** ``Household`` row ever
exists.  The invariant is enforced in two independent layers so neither layer
alone is a single point of failure:

1. **DB-level guard** — the primary key is fixed to ``1`` via a
   ``CheckConstraint("id = 1")``.  Any INSERT with a different ``id`` is
   rejected by the DB engine before the row reaches the table, independent of
   the application layer.

2. **App-layer guard** — ``HouseholdRepository.ensure()`` checks whether a
   row already exists before inserting; if one does it returns the existing
   row without inserting a second one.  Route handlers and services always go
   through the repository (never raw INSERTs).

Note: CHECK constraints are schema-level invariant guards, **not** business
logic, so they are explicitly permitted by roadmap §2.1 / §2.11.  No triggers
or views are used.
"""

from typing import Any

from sqlalchemy import CheckConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Household(Base):
    """Singleton household / workspace configuration.

    Columns
    -------
    id          Fixed to 1 — the CHECK constraint rejects any other value.
    name        Display name for this household (e.g. "Smith Home").
    currency    ISO 4217 currency code (e.g. "USD", "EUR", "CNY").
    timezone    IANA timezone string (e.g. "America/New_York", "Asia/Shanghai").
    settings    Arbitrary JSON blob for future extension (stored as TEXT).
    """

    __tablename__ = "households"
    __table_args__ = (
        # DB-level singleton guard: only id = 1 is allowed.
        CheckConstraint("id = 1", name="ck_households_singleton"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False, default=1)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="My Household")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    # JSON stored as TEXT; SQLAlchemy's JSON type would also work but TEXT keeps
    # the schema simple and portable across SQLite / Postgres.
    settings: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    def __repr__(self) -> str:
        return (
            f"Household(id={self.id!r}, name={self.name!r}, "
            f"currency={self.currency!r}, timezone={self.timezone!r})"
        )

    def settings_dict(self) -> dict[str, Any]:
        """Parse the ``settings`` JSON blob into a Python dict.

        Returns an empty dict when ``settings`` is NULL or an invalid JSON
        string (graceful degradation — the singleton row is trusted data).
        """
        import json

        if not self.settings:
            return {}
        try:
            result = json.loads(self.settings)
            return result if isinstance(result, dict) else {}
        except json.JSONDecodeError:
            return {}
