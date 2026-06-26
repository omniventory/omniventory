"""NoteService — free-text notes lifecycle (M5 Step 3 §4.1).

Responsibilities
----------------
- ``create(model_type, model_id, body, created_by)``
      Validate owner type + existence, then insert a Note row.
- ``get(note_id)``
      Return a Note by PK, or raise 404 (note.not_found).
- ``list_for_owner(model_type, model_id)``
      All Notes for a given owner in chronological order.
- ``update(note_id, body)``
      Patch the body of an existing Note; refreshes ``updated_at``.
- ``delete(note_id)``
      Delete a single Note; raises 404 if not found.
- ``delete_for_owner(model_type, model_id)``
      Cascade helper: remove all Notes for an owner (called from the three
      entity delete services before the owner row is deleted).

Owner type validation and owner existence checks are done via the
``OWNER_TYPES`` registry and ``resolve_owner`` helper from ``app.services.owners``.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.note import Note
from app.repositories.note import NoteRepository
from app.services.owners import resolve_owner


class NoteService:
    """Business-logic facade for Note operations."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = NoteRepository(db)

    # ---------------------------------------------------------------------- #
    # Private helpers                                                          #
    # ---------------------------------------------------------------------- #

    def _get_or_404(self, note_id: int) -> Note:
        """Return a Note or raise 404 (note.not_found)."""
        note = self._repo.get(note_id)
        if note is None:
            raise AppError(
                ErrorCode.NOTE_NOT_FOUND,
                status_code=404,
                params={"id": note_id},
                message=f"Note {note_id} not found.",
            )
        return note

    # ---------------------------------------------------------------------- #
    # CRUD scoped by owner                                                     #
    # ---------------------------------------------------------------------- #

    def create(
        self,
        model_type: str,
        model_id: int,
        body: str,
        *,
        created_by: int | None,
    ) -> Note:
        """Create a new note on an owner.

        Validates that ``model_type`` is in ``OWNER_TYPES`` and that the
        referenced owner exists before inserting.

        Parameters
        ----------
        model_type:
            One of the values in ``OWNER_TYPES``.
        model_id:
            PK of the owner entity.
        body:
            Free-text content (must be non-empty; Pydantic schema enforces this
            at the API boundary).
        created_by:
            The authenticated user's id, or None.

        Raises
        ------
        AppError(validation.invalid_input, 422)
            When ``model_type`` is not in ``OWNER_TYPES``.
        AppError(<owner>.not_found, 404)
            When the owner does not exist.
        """
        resolve_owner(self._db, model_type, model_id)
        return self._repo.create(
            model_type=model_type,
            model_id=model_id,
            body=body,
            created_by=created_by,
        )

    def get(self, note_id: int) -> Note:
        """Return a note by PK, or raise 404 (note.not_found)."""
        return self._get_or_404(note_id)

    def list_for_owner(self, model_type: str, model_id: int) -> list[Note]:
        """Return all Notes for a given owner in chronological order.

        Does NOT validate the owner — intentionally lenient so that this can
        be called in cascade helpers after the owner is already gone, and so
        that a list request for a non-existent owner simply returns [].
        """
        return self._repo.list_for_owner(model_type, model_id)

    def update(self, note_id: int, *, body: str) -> Note:
        """Update the body of an existing note.

        Raises ``note.not_found`` (404) when the note does not exist.
        """
        note = self._get_or_404(note_id)
        return self._repo.update(note, body=body)

    def delete(self, note_id: int) -> None:
        """Delete a single note.

        Raises ``note.not_found`` (404) when the note does not exist.
        """
        note = self._get_or_404(note_id)
        self._repo.delete(note)

    def delete_for_owner(self, model_type: str, model_id: int) -> int:
        """Cascade helper: remove all Notes for an owner.

        Called by entity delete services BEFORE removing the owner row.  Works
        within the same transaction — no post-commit step needed (notes are
        pure DB rows; no filesystem involvement).

        Returns
        -------
        The count of deleted notes.
        """
        return self._repo.delete_for_owner(model_type, model_id)
