"""Repository for the Note table (M5 Step 3).

Pure data access — no business rules here.  Business logic (owner validation,
note-not-found guard, cascade cleanup) lives in ``app.services.note``.

Public methods
--------------
NoteRepository
    create(model_type, model_id, body, created_by)
        Insert and flush a new Note row.
    get(note_id)
        Return a Note by PK, or None.
    list_for_owner(model_type, model_id)
        All Notes for an owner (ordered by created_at ascending).
    update(note, body)
        Apply a body update to an existing Note and flush.
    delete(note)
        Delete a Note row.
    delete_for_owner(model_type, model_id)
        Delete all Notes for an owner; returns the count of deleted rows.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.note import Note


class NoteRepository:
    """Data-access object for the notes table."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ---------------------------------------------------------------------- #
    # Read                                                                     #
    # ---------------------------------------------------------------------- #

    def get(self, note_id: int) -> Note | None:
        """Return a Note by PK, or None if not found."""
        return self._db.get(Note, note_id)

    def list_for_owner(self, model_type: str, model_id: int) -> list[Note]:
        """Return all Notes for a given (model_type, model_id) owner.

        Ordered by ``created_at`` ascending (chronological order).
        """
        stmt = (
            select(Note)
            .where(Note.model_type == model_type, Note.model_id == model_id)
            .order_by(Note.created_at)
        )
        return list(self._db.scalars(stmt).all())

    # ---------------------------------------------------------------------- #
    # Write                                                                    #
    # ---------------------------------------------------------------------- #

    def create(
        self,
        *,
        model_type: str,
        model_id: int,
        body: str,
        created_by: int | None,
    ) -> Note:
        """Insert a new Note row and flush to get its PK."""
        note = Note(
            model_type=model_type,
            model_id=model_id,
            body=body,
            created_by=created_by,
        )
        self._db.add(note)
        self._db.flush()
        return note

    def update(self, note: Note, *, body: str) -> Note:
        """Update the ``body`` of an existing Note and flush.

        SQLAlchemy's ``onupdate=func.now()`` on ``updated_at`` ensures the
        column is refreshed when the row is flushed.
        """
        note.body = body
        self._db.flush()
        return note

    def delete(self, note: Note) -> None:
        """Delete a Note row."""
        self._db.delete(note)
        self._db.flush()

    def delete_for_owner(self, model_type: str, model_id: int) -> int:
        """Delete all Notes for an owner.  Returns the count of deleted rows."""
        notes = self.list_for_owner(model_type, model_id)
        for note in notes:
            self._db.delete(note)
        if notes:
            self._db.flush()
        return len(notes)
