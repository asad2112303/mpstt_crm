"""Pydantic schemas for auth and user administration."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str | None
    role: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class MeOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str | None
    role: str
    aal: str


class InviteUserIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=150)
    role: str = Field(pattern="^(admin|user)$")
    # "invite" emails a link (needs working SMTP); "password" creates the login
    # directly and returns a one-time password for the admin to hand over.
    mode: str = Field(default="invite", pattern="^(invite|password)$")
    password: str | None = Field(default=None, min_length=10, max_length=72)


class UpdateUserIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    role: str | None = Field(default=None, pattern="^(admin|user)$")
    is_active: bool | None = None
