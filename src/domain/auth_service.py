# src/domain/auth_service.py
import logging
from datetime import datetime, timezone
from fastapi import HTTPException, status
from src.integrations import auth_repository
from src.schemas.auth import UserRegisterRequest, UserLoginRequest
from src.integrations.supabase_client import supabase

logger = logging.getLogger(__name__)

class AuthService:
    """
    Handles user authentication workflows, coordinating between external auth 
    credentials and internal application profile records through repository adapters.
    """

    @classmethod
    def register_user(cls, payload: UserRegisterRequest) -> dict:
        """
        Registers a new user via Supabase Auth, provisions their profile metadata, 
        and explicitly syncs an entry into the public `user_account` database table.
        """
        email = payload.email
        password = payload.password
        full_name = payload.full_name

        try:
            response = auth_repository.auth_sign_up(
                email=email,
                password=password,
                full_name=full_name
            )
            
            user = getattr(response, "user", None)
            session = getattr(response, "session", None)

            if not user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Registration failed. User object not returned."
                )

            user_id = str(user.id)

            if not session:
                logger.info(f"Registration successful for {email}. Email confirmation pending.")
                return {
                    "success": True,
                    "message": "Registration successful! Please check your email to confirm your account before signing in.",
                    "requires_confirmation": True,
                    "access_token": None,
                    "user": {
                        "id": user_id,
                        "email": email,
                        "full_name": full_name
                    }
                }

            logger.info(f"User successfully registered and authenticated: {email}")
            return {
                "success": True,
                "message": "Registration successful.",
                "requires_confirmation": False,
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
                "user": {
                    "id": user_id,
                    "email": email,
                    "full_name": full_name
                }
            }

        except Exception as e:
            error_msg = str(e).lower()
            if "already registered" in error_msg or "already exists" in error_msg or "user already registered" in error_msg:
                logger.warning(f"Registration attempt failed - email already in use: {email}")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This email is already registered. Please sign in or use a different email address."
                )
            
            if isinstance(e, HTTPException):
                raise e

            logger.error(f"Unexpected Supabase auth registration error for {email}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Supabase auth registration failed: {str(e)}"
            )
            
    @staticmethod
    def login_user(payload: UserLoginRequest) -> dict:
        """
        Authenticates an existing user via Supabase Auth password verification, 
        updates their last login timestamp in the database, and returns an active token.
        """
        try:
            response = auth_repository.auth_sign_in(payload.email, payload.password)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid email or password: {str(e)}"
            )

        if not response or not response.session or not response.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password."
            )

        user_id = response.user.id
        access_token = response.session.access_token

        try:
            auth_repository.update_last_login(user_id, datetime.now(timezone.utc).isoformat())
        except Exception as db_err:
            logger.warning("Failed to update last login timestamp: %s", str(db_err))

        return {
            "user_id": user_id,
            "email": response.user.email,
            "access_token": access_token,
            "message": "Login successful."
        }