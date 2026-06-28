"""In-memory rate limiter with exponential backoff (M6 Step 7 §4.6).

``RateLimiter`` tracks, per ``(scope, key)``, recent failures within a rolling
window and an exponential lockout.  Only failures count toward lockout; a
success via ``clear()`` resets all state for that key.

Policy (constants below, sane defaults)
----------------------------------------
- Allow up to ``N`` failures per rolling ``window`` seconds.
- Beyond that, lockout that **doubles per subsequent violation** and is capped:
  k-th lockout = ``min(base_lockout * 2^(k-1), cap)``.
- A success (``clear()``) resets both the failure counter and the violation count.

Thread safety
-------------
All state mutations are protected by a single ``threading.Lock``.  The
limiter is designed for the single-process, single-container deployment.

Injectable clock
----------------
``now`` defaults to ``time.monotonic``.  Pass a fake callable for tests to
advance time without sleeping.

Module-level singleton + accessor
----------------------------------
``_limiter``       — the process-level singleton (uses ``time.monotonic``).
``get_rate_limiter()`` — returns ``_limiter``; used by the route dependency.
``reset()``        — clears all state (test isolation; see ``tests/conftest.py``).
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from app.core.errors import AppError, ErrorCode

# ---------------------------------------------------------------------------
# Policy constants
# ---------------------------------------------------------------------------

#: Number of failures allowed within the rolling window before lockout.
_THRESHOLD: int = 5

#: Rolling-window duration in seconds.
_WINDOW: float = 300.0

#: Duration (seconds) of the first lockout (1st violation).
_BASE_LOCKOUT: float = 30.0

#: Maximum lockout duration (seconds) — 30 minutes.
_CAP: float = 1800.0


# ---------------------------------------------------------------------------
# Per-key state
# ---------------------------------------------------------------------------


@dataclass
class _State:
    """Mutable state for a single ``(scope, key)`` slot."""

    #: Monotonic timestamps of recent failures (within ``_WINDOW``).
    failures: list[float] = field(default_factory=list)

    #: Number of lockouts imposed so far (determines the next lockout duration).
    violations: int = 0

    #: Monotonic timestamp until which the key is locked out (0 = not locked).
    lockout_until: float = 0.0


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


class RateLimiter:
    """In-memory, per-``(scope, key)`` rate limiter with exponential backoff.

    Parameters
    ----------
    now:
        A callable that returns the current time as a float (monotonic seconds).
        Defaults to ``time.monotonic``.  Inject a fake clock in tests so time
        can be advanced without real sleeps.
    """

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._state: dict[tuple[str, str], _State] = defaultdict(_State)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, scope: str, key: str) -> None:
        """Raise 429 if ``(scope, key)`` is currently locked out.

        Must be called **before** the handler performs any credential check.
        If the key is not locked out, returns silently.

        Parameters
        ----------
        scope:
            Logical endpoint group, e.g. ``"login"``, ``"invite_accept"``.
        key:
            Per-client discriminator, typically the client IP or
            ``"<ip>:<user_id>"`` for change-password.

        Raises
        ------
        AppError
            ``auth.rate_limited`` / 429 with ``Retry-After`` header and
            ``params.retry_after_seconds`` when the key is locked out.
        """
        with self._lock:
            state = self._state[(scope, key)]
            t = self._now()
            if state.lockout_until > t:
                remaining_secs = state.lockout_until - t
                retry_after = max(1, math.ceil(remaining_secs))
                raise AppError(
                    ErrorCode.AUTH_RATE_LIMITED,
                    status_code=429,
                    params={"retry_after_seconds": retry_after},
                    headers={"Retry-After": str(retry_after)},
                )

    def register_failure(self, scope: str, key: str) -> None:
        """Record a failed attempt for ``(scope, key)``.

        Trims failures outside the rolling window, appends the current
        timestamp, then imposes a lockout when failures-in-window reach
        ``_THRESHOLD``.  Each subsequent lockout doubles in duration, capped
        at ``_CAP``.

        Must be called **after** a failed credential check / bad-token
        attempt, before raising the application error.
        """
        with self._lock:
            t = self._now()
            state = self._state[(scope, key)]

            # Drop failures that have fallen outside the rolling window.
            state.failures = [f for f in state.failures if t - f < _WINDOW]
            state.failures.append(t)

            if len(state.failures) >= _THRESHOLD:
                # Threshold reached — impose/extend lockout.
                state.violations += 1
                lockout_secs = min(_BASE_LOCKOUT * (2 ** (state.violations - 1)), _CAP)
                state.lockout_until = t + lockout_secs
                # Clear failure list so the next batch after lockout starts fresh.
                state.failures = []

    def clear(self, scope: str, key: str) -> None:
        """Reset all rate-limit state for ``(scope, key)`` on a successful attempt.

        Removes the key's failure list, violation count, and lockout timestamp.
        """
        with self._lock:
            self._state.pop((scope, key), None)

    def reset(self) -> None:
        """Clear **all** state across every key — for test isolation only.

        Call this (or register an autouse fixture that calls it) before each
        test to prevent failure counts accumulated in previous tests from
        locking out test clients.
        """
        with self._lock:
            self._state.clear()


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_limiter: RateLimiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """Return the process-level ``RateLimiter`` singleton.

    Used by ``auth_rate_limit`` (``app/api/deps.py``) and tests.
    Tests should call ``get_rate_limiter().reset()`` (or use the autouse
    fixture in ``tests/conftest.py``) to avoid cross-test state leakage.
    """
    return _limiter
