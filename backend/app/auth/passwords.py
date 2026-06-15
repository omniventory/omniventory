"""Password hashing and verification using argon2.

``argon2-cffi`` is the backing library (installed via pyproject.toml).
This module exposes two functions and nothing else:

``hash_password(plaintext)``
    Returns an argon2 hash string.  Plaintext is never stored or logged.

``verify_password(plaintext, hashed)``
    Returns True if ``plaintext`` matches the hash, False otherwise.
    A failed verification (wrong password) returns False; it does NOT raise.

Why argon2?
-----------
Argon2 is the Password Hashing Competition winner and the current OWASP
recommendation.  It is memory-hard (resistant to GPU/ASIC brute-force) and
has good defaults out of the box.  ``argon2-cffi`` wraps the reference C
implementation cleanly for Python.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# One shared PasswordHasher instance with argon2-cffi's library defaults.
# The defaults (time_cost=3, memory_cost=65536, parallelism=4, hash_len=32)
# meet OWASP minimum recommendations.  Increase for production hardening in M6.
_ph = PasswordHasher()

# A real (but intentionally garbage) argon2 hash used for constant-time
# dummy verification when the looked-up user does not exist.
# Generated once at module load so the timing behaviour is consistent.
# The hash will never match any real password — it is just for timing parity.
_DUMMY_HASH: str = _ph.hash("__omniventory_timing_dummy__")


def hash_password(plaintext: str) -> str:
    """Hash ``plaintext`` with argon2 and return the encoded hash string.

    The returned string is self-contained: it encodes the algorithm parameters
    and salt, so ``verify_password`` needs no external state to verify it.
    """
    return _ph.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    """Return True if ``plaintext`` matches ``hashed``, False otherwise.

    Returns False for both a wrong password (``VerifyMismatchError``) and for
    a corrupted / invalid hash string (``InvalidHashError``).  This makes the
    function safe to call with any hash value (including the dummy hash used
    for timing protection on unknown-user login attempts).
    """
    try:
        _ph.verify(hashed, plaintext)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


def dummy_verify(plaintext: str) -> None:
    """Perform a constant-time dummy verification for unknown-user timing parity.

    Call this when a user is not found during login to consume roughly the
    same time as a real ``verify_password`` call, preventing user-enumeration
    via response timing.
    """
    verify_password(plaintext, _DUMMY_HASH)
