"""Pydantic request/response schemas for the auth endpoints.

Schemas are kept thin: they describe the wire format only.  Business logic
lives in the service/repository layer.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class LoginRequest(BaseModel):
    """Body for POST /auth/login."""

    email: str
    password: str


class UserResponse(BaseModel):
    """Public representation of a User (no password_hash).

    ``preferred_language`` is nullable.  NULL means the user has never
    explicitly chosen a language; the client resolves via its own chain.
    Added in M1.5 Step 2.
    """

    id: int
    email: str
    role: str
    is_active: bool
    created_at: datetime
    preferred_language: str | None = None

    model_config = {"from_attributes": True}


class MeResponse(BaseModel):
    """Response body for GET /auth/me."""

    user: UserResponse


class MessageResponse(BaseModel):
    """Generic message response (used for logout)."""

    message: str


class SetupStatusResponse(BaseModel):
    """Response body for GET /auth/setup-status."""

    setup_required: bool


class SetupRequest(BaseModel):
    """Body for POST /auth/setup — create the first admin user."""

    email: str
    password: str


class UserPreferencesUpdate(BaseModel):
    """Body for PATCH /api/auth/me — update per-user preferences.

    All fields are optional and PATCH-style.  An omitted field is a no-op and
    does NOT overwrite an existing value.  Setting a field to ``null``
    explicitly unsets it (re-inherits client-side resolution chain).

    Null-vs-omitted semantics
    -------------------------
    We must distinguish three cases for ``preferred_language``:
    - Field **omitted** from the JSON body → no-op (do not touch the stored value).
    - Field set to **null** explicitly → write NULL (explicit unset).
    - Field set to a **string** → validate + write.

    Pydantic v2's ``model_fields_set`` correctly tracks which fields were
    explicitly present in the raw input, including when the value is ``null``.
    Because ``preferred_language`` defaults to ``None``, an omitted key does
    *not* appear in ``model_fields_set``, while ``{"preferred_language": null}``
    *does* — allowing the route to distinguish omission from explicit null.
    The route checks ``"preferred_language" in body.model_fields_set`` instead
    of relying on a private tracking field.
    """

    preferred_language: str | None = None

    model_config = {"json_schema_extra": {"examples": [{"preferred_language": "zh"}]}}
