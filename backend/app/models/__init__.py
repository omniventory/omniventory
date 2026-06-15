"""SQLAlchemy models package.

Import all models here so that Alembic's ``env.py`` (which imports this
package) discovers every table when generating / running migrations.
"""

from app.models.household import Household

__all__ = ["Household"]
