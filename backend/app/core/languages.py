"""Supported language codes for the Omniventory backend.

This module defines the canonical set of supported BCP-47 language codes.
The validator in the PATCH /api/auth/me endpoint checks incoming
``preferred_language`` values against this set.

Design decisions (M1.5 §2, roadmap §2.11):
- The set is enforced **app-layer** (here), not via a DB CHECK constraint,
  so adding a new language only requires updating this file (not a migration).
- The frontend hardcodes the same list (``src/i18n/languages.ts``); keeping
  both in sync is a 2-line concern flagged for a future ``/api/i18n/languages``
  endpoint if the list grows (M1.5 §12).
- M1.5 ships exactly ``'en'`` and ``'zh'``.  The stored column is wide enough
  (``String(16)``) to hold BCP-47 subtags later without a migration.
- This module is **not** exposed over the API in M1.5.
"""

SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "zh")
