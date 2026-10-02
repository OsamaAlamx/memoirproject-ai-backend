"""
@file src/core/auth.py
@description FastAPI security dependency for high-performance local JWT verification 
via Supabase JWKS, eliminating remote auth network round-trips and handling exceptions cleanly.
"""

import jwt
from jwt import PyJWKClient
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from src.core.config import SUPABASE_JWKS_URL

security = HTTPBearer()

jwks_client = PyJWKClient(SUPABASE_JWKS_URL) if SUPABASE_JWKS_URL else None


def get_user_id(current_user: dict | str | None) -> str:
    """Single place that unwraps the auth dependency to a user id string."""
    if isinstance(current_user, dict):
        return (
            current_user.get("user_id")
            or current_user.get("id")
            or current_user.get("sub")
            or ""
        )
    return str(current_user or "")


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """
    Validates the incoming Bearer JWT locally against the project's JWKS endpoint 
    without triggering a remote network round-trip to Supabase Auth on every request.
    """
    token = credentials.credentials
    try:
        if not jwks_client:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="SUPABASE_JWKS_URL is not configured for local JWT validation."
            )

        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience="authenticated",
            leeway=60,
            options={"require": ["exp", "sub"]},
        )

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload: missing subject identifier (sub)."
            )

        return {
            "user_id": user_id,
            "email": payload.get("email"),
            "role": payload.get("role"),
            "claims": payload
        }

    except HTTPException:
        raise
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials."
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed."
        )