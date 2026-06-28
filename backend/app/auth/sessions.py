"""Server-side session management.

Sessions are stored in the ``sessions`` table.  The cookie carries only
the opaque session id — no user data.

Public API
----------
``create(db, user_id)``                          Create a new session row; return its id.
``verify(db, session_id)``                       Look up and validate; return the Session or None.
``revoke(db, session_id)``                       Delete the session row (logout / revocation).
``revoke_all_for_user(db, user_id, *, ...)``     Bulk-delete all sessions for a user (M6 Step 3).
``purge_expired(db)``                            Delete all rows whose ``expires_at`` has passed.

Session lifetime
----------------
Sessions use a fixed TTL (``SESSION_TTL_HOURS`` = 24 h) with a **throttled
sliding-window refresh** implemented in M6 Step 7: ``verify`` extends
``expires_at`` and updates ``last_seen_at`` when fewer than half of the TTL
seconds remain (< 12 h left), keeping active sessions alive without
re-authenticating.  "Remember me" (extended TTL) remains deferred.

Expired-session cleanup / write semantics
-----------------------------------------
``verify`` is **not a pure read** when the sliding-window condition is met:
it calls ``db.flush()`` to stage the refresh write.  The flush is committed
by ``get_db``'s success path; an erroring request rolls back the flush, so
the session is simply not extended that round — acceptable best-effort
semantics (active sessions are rarely within 12 h of expiry, and a single
missed extension is harmless).  Expired rows are cleaned up by
``purge_expired``, called on application startup (lifespan hook in
``app/main.py``).
"""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session as DBSession

from app.models.session import Session

# Fixed TTL; sliding-window refresh implemented in M6 Step 7.  "Remember me" (extended TTL) remains deferred.
SESSION_TTL_HOURS: int = 24


def _now_utc() -> datetime:
    """Return the current time in UTC (timezone-aware)."""
    return datetime.now(UTC)


def _as_utc(dt: datetime) -> datetime:
    """Ensure ``dt`` is timezone-aware (UTC).

    SQLite stores datetimes without timezone info, so values read back from
    the DB are offset-naive.  This function attaches UTC if the value has no
    tzinfo, making comparisons with offset-aware datetimes safe.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _new_session_id() -> str:
    """Generate a cryptographically random, URL-safe session token."""
    # token_urlsafe(32) gives 256 bits of entropy; more than sufficient.
    return secrets.token_urlsafe(32)


def create(db: DBSession, user_id: int) -> Session:
    """Create a new server-side session for ``user_id``.

    Returns the newly-created ``Session`` ORM object.  The session ``id`` is
    the value to store in the cookie.

    The caller must commit (or yield from ``get_db``) to persist the row.
    """
    now = _now_utc()
    session = Session(
        id=_new_session_id(),
        user_id=user_id,
        created_at=now,
        expires_at=now + timedelta(hours=SESSION_TTL_HOURS),
        last_seen_at=now,
    )
    db.add(session)
    db.flush()  # Assign id and raise IntegrityError now (before commit).
    return session


def verify(db: DBSession, session_id: str) -> Session | None:
    """Look up and validate a session by its id.

    Returns the ``Session`` ORM object if the session exists and has not
    expired; returns ``None`` if the session is missing or expired.

    This function does NOT delete expired rows; expired rows are handled by
    ``purge_expired`` (called on app startup).  This avoids the rollback
    trap: when a caller raises an exception after this function returns
    ``None``, the ``get_db`` error handler would roll back any pending flush.

    Sliding-window expiry (M6 Step 7)
    -----------------------------------
    When a valid session has less than half the TTL remaining
    (``expires_at - now < TTL/2``), this function refreshes the session:

    - ``expires_at ← now + TTL``
    - ``last_seen_at ← now``

    The update is ``flush``-ed but not committed here.  It is committed by
    ``get_db``'s success-commit path on non-erroring requests.  If the
    request raises an exception, the refresh is rolled back — this is
    acceptable best-effort (active users are rarely near expiry and a single
    missed refresh is harmless).

    The half-life throttle ensures most requests (with ample TTL remaining)
    do **not** write to the DB, keeping the overhead low.

    Expired sessions still return ``None`` (unchanged behaviour).
    """
    session = db.get(Session, session_id)
    if session is None:
        return None

    now = _now_utc()
    if now >= _as_utc(session.expires_at):
        # Expired — reject without deleting.  purge_expired handles cleanup.
        return None

    # Sliding-window: refresh if less than half the TTL remains.
    half_ttl = timedelta(hours=SESSION_TTL_HOURS / 2)
    if _as_utc(session.expires_at) - now < half_ttl:
        session.expires_at = now + timedelta(hours=SESSION_TTL_HOURS)
        session.last_seen_at = now
        db.flush()

    return session


def revoke(db: DBSession, session_id: str) -> None:
    """Delete the session row, effectively logging the user out.

    No-op if the session does not exist (idempotent revocation).
    The caller must commit to persist the deletion.
    """
    session = db.get(Session, session_id)
    if session is not None:
        db.delete(session)
        db.flush()


def revoke_all_for_user(
    db: DBSession,
    user_id: int,
    *,
    except_session_id: str | None = None,
) -> int:
    """Bulk-delete all sessions for ``user_id``, optionally keeping one.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    user_id:
        The user whose sessions are revoked.
    except_session_id:
        When provided, this session is kept alive (used by change-password to
        keep the current session while revoking all other sessions).

    Returns the number of rows deleted.

    Implementation notes
    --------------------
    Uses ``synchronize_session=False`` + ``expire_all()`` for the same reason
    as ``purge_expired`` — avoids the tz-naive comparison trap and keeps the
    identity map consistent after a bulk DELETE (M6 §4.3).

    Called by:
    - ``InvitationService.accept_reset`` — revoke ALL sessions for the user.
    - ``InvitationService.change_password`` — revoke OTHER sessions, keep the
      current one (pass ``except_session_id``).
    """
    from sqlalchemy import CursorResult, delete

    stmt = delete(Session).where(Session.user_id == user_id)
    if except_session_id is not None:
        stmt = stmt.where(Session.id != except_session_id)

    raw = db.execute(stmt, execution_options={"synchronize_session": False})
    db.expire_all()
    db.flush()
    cursor: CursorResult[tuple[()]] = raw  # type: ignore[assignment]
    count: int = cursor.rowcount if cursor.rowcount is not None else 0
    return count


def purge_expired(db: DBSession) -> int:
    """Delete all expired session rows.

    Returns the number of rows deleted.  Called on application startup
    (lifespan hook in ``app/main.py``) to keep the sessions table tidy.

    Implementation note
    -------------------
    We use ``synchronize_session=False`` on the bulk DELETE to skip
    SQLAlchemy's in-memory WHERE-clause evaluation.  That evaluation would
    fail with ``TypeError`` when the DB returns offset-naive datetimes
    (SQLite strips tzinfo on round-trip) and we compare them to the
    offset-aware ``now``.  With ``synchronize_session=False`` SQLAlchemy
    issues the SQL DELETE directly; we then call ``db.expire_all()`` so any
    subsequently-accessed objects are refreshed from the DB rather than stale
    identity-map state.
    """
    from sqlalchemy import CursorResult, delete

    now = _now_utc()
    raw = db.execute(
        delete(Session).where(Session.expires_at < now),
        execution_options={"synchronize_session": False},
    )
    db.expire_all()  # Evict stale identity-map entries after the bulk DELETE.
    db.flush()
    # CursorResult.rowcount is the number of affected rows.
    cursor: CursorResult[tuple[()]] = raw  # type: ignore[assignment]
    count: int = cursor.rowcount if cursor.rowcount is not None else 0
    return count
