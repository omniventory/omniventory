"""Pydantic request/response schemas for Note endpoints (M5 Step 3).

Schemas are thin wire DTOs; business logic lives in the service layer.
All response schemas use ``from_attributes = True`` so they can be constructed
directly from SQLAlchemy ORM objects.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class NoteResponse(BaseModel):
    """Public representation of a Note."""

    id: int
    model_type: str
    model_id: int
    body: str
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NoteCreate(BaseModel):
    """Body for POST /notes."""

    model_type: str = Field(..., min_length=1, max_length=32)
    model_id: int
    body: str = Field(..., min_length=1)


class NoteUpdate(BaseModel):
    """Body for PATCH /notes/{id} — only body is patchable."""

    body: str = Field(..., min_length=1)
