import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
)

from app.models.user import UserRole

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128  # bounds argon2 work per request


def _check_password_strength(value: str) -> str:
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValueError("Password must contain at least one letter and one digit")
    return value


Password = Annotated[
    str,
    StringConstraints(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH),
    AfterValidator(_check_password_strength),
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
CompanyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
NormalizedEmail = Annotated[EmailStr, AfterValidator(lambda v: v.lower())]


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: NormalizedEmail
    password: Password
    full_name: Name
    company_name: CompanyName
    # Public sign-up always creates a BUYER. Suppliers join only via an email invite.


class InviteTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Sent in the body (not the URL) so tokens don't end up in access logs.
    token: str = Field(min_length=20, max_length=200)


class InviteInfo(BaseModel):
    email: str
    invited_by_company: str
    expires_at: datetime


class AcceptInviteRequest(InviteTokenRequest):
    password: Password
    full_name: Name
    company_name: CompanyName


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: NormalizedEmail
    # No strength rules on login: just bound the size.
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    company_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


class AuthResponse(BaseModel):
    """Access token for the Authorization header. The refresh token is set as an
    httpOnly cookie and is never exposed to JavaScript."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth2 token type, not a secret
    expires_in: int = Field(description="Access token lifetime in seconds")
    user: UserRead
