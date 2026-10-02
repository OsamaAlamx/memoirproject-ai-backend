"""
@file models/auth.py
@description Pydantic models for user authentication and registration requests.
"""

from pydantic import BaseModel, EmailStr, Field, field_validator

DISPOSABLE_DOMAINS = frozenset({
    "tempmail.com", "10minutemail.com", "guerrillamail.com", "mailinator.com",
    "yopmail.com", "trashmail.com", "fakeinbox.com", "getnada.com",
})

class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=10, max_length=128, description="Password must be at least 10 characters long.")
    full_name: str = Field(..., min_length=1, description="User's full name for profile setup.")

    @field_validator("email")
    @classmethod
    def _reject_disposable(cls, v: str) -> str:
        domain = v.split("@")[-1].lower()
        if domain in DISPOSABLE_DOMAINS:
            raise ValueError("Disposable email addresses are not allowed.")
        return v

class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str