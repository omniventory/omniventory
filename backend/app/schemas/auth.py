"""Pydantic request/response schemas for the auth endpoints.

Schemas are kept thin: they describe the wire format only.  Business logic
lives in the service/repository layer.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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
    reminder_best_before_lead_days: int | None = None  # M4: per-user lead override; NULL = inherit
    reminder_warranty_lead_days: int | None = None  # M4: per-user lead override; NULL = inherit

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
    explicitly unsets it (clears the override, re-inheriting the next level in
    the resolution chain).

    Null-vs-omitted semantics
    -------------------------
    Pydantic v2's ``model_fields_set`` correctly tracks which fields were
    explicitly present in the raw input, including when the value is ``null``.
    Because all fields default to ``None``, an omitted key does *not* appear in
    ``model_fields_set``, while ``{"field": null}`` *does* — allowing the route
    to distinguish omission from explicit null.

    The route checks ``"<field>" in body.model_fields_set`` for each field:
    - **Omitted** → no-op (do not touch the stored value).
    - **Null** explicitly → write NULL to DB (remove the override, inherit up).
    - **Value** → validate + write.

    This applies uniformly to:
    - ``preferred_language``: NULL → client resolves (localStorage → navigator → 'en').
    - ``reminder_best_before_lead_days``: NULL → inherit per-user fallback chain (§4.3).
    - ``reminder_warranty_lead_days``: NULL → inherit per-user fallback chain (§4.3).
    """

    preferred_language: str | None = None
    reminder_best_before_lead_days: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Per-user best-before lead-time override in days (M4). "
            "``NULL`` = remove the override, inherit global default (§4.3). "
            "Must be ≥ 0 when provided (0 = fire on the target date itself). "
            "Omitting the field is a no-op; ``null`` explicitly clears the override."
        ),
    )
    reminder_warranty_lead_days: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Per-user warranty-expiry lead-time override in days (M4). "
            "``NULL`` = remove the override, inherit global default (§4.3). "
            "Must be ≥ 0 when provided (0 = fire on the target date itself). "
            "Omitting the field is a no-op; ``null`` explicitly clears the override."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "preferred_language": "zh",
                    "reminder_best_before_lead_days": 5,
                    "reminder_warranty_lead_days": 14,
                }
            ]
        }
    }
