"""Note CRUD endpoints (M5 Step 3).

All endpoints require a valid session.

Routes (all under the api_prefix, e.g. /api):
    GET    /notes?model_type=&model_id=   List notes on an owner (chronological).
    POST   /notes                         Create a new note on an owner.
    PATCH  /notes/{id}                    Update the note body.
    DELETE /notes/{id}                    Delete a note.

Error contract:
    401  No/invalid session.
    404  Note not found / owner not found.
    422  Bad model_type (validation.invalid_input).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_edit
from app.core.context import RequestContext, get_authenticated_context
from app.core.errors import ErrorResponse
from app.db.session import get_db
from app.models.user import User
from app.schemas.note import NoteCreate, NoteResponse, NoteUpdate
from app.services.note import NoteService

_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

router = APIRouter(prefix="/notes", tags=["notes"], responses=_ERROR_RESPONSES)


def _get_service(db: Annotated[Session, Depends(get_db)]) -> NoteService:
    """Dependency: build and return a NoteService."""
    return NoteService(db)


@router.get("", response_model=list[NoteResponse])
def list_notes(
    _ctx: Annotated[RequestContext, Depends(get_authenticated_context)],
    service: Annotated[NoteService, Depends(_get_service)],
    model_type: Annotated[str, Query(description="Owner type.")],
    model_id: Annotated[int, Query(description="Owner PK.")],
) -> list[NoteResponse]:
    """List all notes attached to a given owner (model_type + model_id).

    Returns notes in chronological order (oldest first).
    Does not validate the owner's existence — an unknown owner returns an
    empty list (consistent with the lenient list semantics used for tags).
    """
    notes = service.list_for_owner(model_type, model_id)
    return [NoteResponse.model_validate(n) for n in notes]


@router.post("", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
def create_note(
    body: NoteCreate,
    ctx: Annotated[RequestContext, Depends(get_authenticated_context)],
    _: Annotated[User, Depends(require_edit)],
    service: Annotated[NoteService, Depends(_get_service)],
    db: Annotated[Session, Depends(get_db)],
) -> NoteResponse:
    """Create a new note on an owner.

    Returns 422 if model_type is invalid, 404 if the owner does not exist.
    """
    user_id = ctx.user.id if ctx.user is not None else None
    note = service.create(
        body.model_type,
        body.model_id,
        body.body,
        created_by=user_id,
    )
    db.commit()
    db.refresh(note)
    return NoteResponse.model_validate(note)


@router.patch("/{note_id}", response_model=NoteResponse)
def update_note(
    note_id: int,
    body: NoteUpdate,
    _ctx: Annotated[RequestContext, Depends(get_authenticated_context)],
    _: Annotated[User, Depends(require_edit)],
    service: Annotated[NoteService, Depends(_get_service)],
    db: Annotated[Session, Depends(get_db)],
) -> NoteResponse:
    """Update the body of an existing note.

    Returns 404 if the note does not exist.
    """
    note = service.update(note_id, body=body.body)
    db.commit()
    db.refresh(note)
    return NoteResponse.model_validate(note)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    note_id: int,
    _ctx: Annotated[RequestContext, Depends(get_authenticated_context)],
    _: Annotated[User, Depends(require_edit)],
    service: Annotated[NoteService, Depends(_get_service)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Delete a note.

    Returns 404 if the note does not exist.
    """
    service.delete(note_id)
    db.commit()
