"""
@file auth_repository.py
@description Data access layer adapter module managing direct Supabase Auth 
sign-up/sign-in flows and user account profile table synchronization.
"""

from src.integrations.supabase_client import supabase, supabase_admin
from src.core.config import settings


def auth_sign_up(email: str, password: str, full_name: str):
    """
    Invokes Supabase Auth registration to provision user credentials and metadata.

    Args:
        email (str): The user's email address.
        password (str): The user's password.
        full_name (str): The user's full name.

    Returns:
        Any: The Supabase auth response object.
    """
    return supabase.auth.sign_up({
        "email": email,
        "password": password,
        "options": {
            "email_redirect_to": f"{settings.frontend_url.rstrip('/')}/login",
            "data": {
                "full_name": full_name
            }
        }
    })


def auth_sign_in(email: str, password: str):
    """
    Authenticates a user against Supabase Auth using email and password.

    Args:
        email (str): The user's email address.
        password (str): The user's password.

    Returns:
        Any: The Supabase auth response object containing session and user data.
    """
    return supabase.auth.sign_in_with_password({
        "email": email,
        "password": password
    })


def update_last_login(user_id: str, timestamp: str):
    """
    Updates the last login timestamp record for a specific user account.

    Args:
        user_id (str): The unique user ID.
        timestamp (str): The ISO-formatted UTC timestamp string.

    Returns:
        Any: The database query response object.
    """
    return supabase.table("user_account").update({
        "last_login_at": timestamp
    }).eq("id", user_id).execute()


def ensure_user_account(user_id: str, email: str, full_name: str):
    """
    Upserts the public `user_account` profile row for an auth user.

    `memoir.created_by_user_id` FK-references `user_account(id)`, but nothing
    in the signup flow created that row (Supabase Auth only populates
    `auth.users`). Without this, the first memoir insert fails with 23503.
    Uses the service-role client to bypass RLS.
    """
    return supabase_admin.table("user_account").upsert({
        "id": user_id,
        "email": email,
        "full_name": full_name or "Memoir Owner",
    }, on_conflict="id").execute()