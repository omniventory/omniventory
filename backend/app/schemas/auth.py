"""Pydantic request/response schemas for the auth endpoints.

Schemas are kept thin: they describe the wire format only.  Business logic
lives in the service/repository layer.
"""

from datetime import datetime

from pydantic import BaseModel


class LoginRequest(BaseModel):
    """Body for POST /auth/login."""

    email: str
    password: str


class UserResponse(BaseModel):
    """Public representation of a User (no password_hash)."""

    id: int
    email: str
    role: str
    is_active: bool
    created_at: datetime

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
