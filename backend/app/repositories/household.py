"""Repository for the Household singleton.

All DB access to the ``households`` table goes through this class.  Route
handlers and services **must not** issue raw queries against ``households``;
they call ``HouseholdRepository`` methods instead.

The two public methods are:

``get()``
    Return the singleton ``Household`` or ``None`` if it does not exist yet.

``ensure()``
    Return the singleton, creating it with sane defaults if it is absent.
    This is the app-layer half of the two-layer singleton invariant: if a row
    already exists the method returns it without attempting a second INSERT.
    (The DB-level ``CHECK(id = 1)`` is the other half.)

``db_ping()``
    Execute a trivial ``SELECT 1`` to confirm DB reachability.  Used by the
    health endpoint.  Wrapping it here keeps raw SQL out of route handlers.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.household import Household


class HouseholdRepository:
    """Data-access object for the Household singleton."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ---------------------------------------------------------------------- #
    # Read                                                                     #
    # ---------------------------------------------------------------------- #

    def get(self) -> Household | None:
        """Return the singleton Household row, or None if it does not exist."""
        return self._db.get(Household, 1)

    # ---------------------------------------------------------------------- #
    # Write (singleton guarantee)                                              #
    # ---------------------------------------------------------------------- #

    def ensure(
        self,
        *,
        name: str = "My Household",
        currency: str = "USD",
        timezone: str = "UTC",
        settings: str | None = None,
    ) -> Household:
        """Return the singleton Household, creating it with defaults if absent.

        App-layer singleton guard:
        - If id=1 already exists → return it immediately (no INSERT attempted).
        - If it does not exist → create and flush a new row with id=1.

        The DB-level ``CHECK(id = 1)`` provides a second, independent guard:
        any accidental INSERT with a different id is rejected at the DB level.
        """
        household = self.get()
        if household is not None:
            return household

        household = Household(
            id=1,
            name=name,
            currency=currency,
            timezone=timezone,
            settings=settings,
        )
        self._db.add(household)
        self._db.flush()  # Assign id / raise IntegrityError now (before commit).
        return household

    # ---------------------------------------------------------------------- #
    # Health probe                                                             #
    # ---------------------------------------------------------------------- #

    def db_ping(self) -> bool:
        """Execute ``SELECT 1`` to verify DB connectivity.

        Returns True on success; propagates exceptions on failure (the caller
        converts those to an appropriate HTTP error or health status).
        This method exists so the health route has no raw SQL of its own.
        """
        self._db.execute(text("SELECT 1"))
        return True
