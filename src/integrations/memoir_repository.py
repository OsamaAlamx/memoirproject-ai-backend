"""
@file memoir_repository.py
@description Data access layer adapter module handling direct Supabase queries 
and persistence for user accounts, memoirs, and memoir participant roles.
"""

from src.integrations.supabase_client import supabase_admin
from datetime import datetime, timezone


def fetch_user_account(user_id: str):
    """
    Fetches user account profile details from the database.

    Args:
        user_id (str): The unique identifier of the user account.

    Returns:
        Any: The database query result containing profile records.
    """
    return supabase_admin.table("user_account").select("full_name, email").eq("id", user_id).execute()


def insert_memoir(memoir_data: dict):
    """
    Inserts a new root memoir container record into the database.

    Args:
        memoir_data (dict): The dictionary containing validated memoir properties.

    Returns:
        Any: The database response object containing the inserted memoir record.
    """
    return supabase_admin.table("memoir").insert(memoir_data).execute()


def insert_memoir_participant(participant_data: dict):
    """
    Registers a user as a participant in a memoir container.

    Args:
        participant_data (dict): The dictionary containing participant mapping data.

    Returns:
        Any: The database response object from the participant insertion.
    """
    return supabase_admin.table("memoir_participant").insert(participant_data).execute()

def delete_memoir_record(memoir_id: str):
    """Deletes an orphan memoir during a failed transaction rollback."""
    return supabase_admin.table("memoir").delete().eq("id", memoir_id).execute()

def fetch_live_memoir_data(memoir_id: str):
    """
    Fetches the complete memoir structure for the live memoir view:
    memoir metadata, chapters, memories with embedded media, transcripts,
    participants, and photo gallery assets.
    """
    # 1. Memoir metadata
    memoir_res = supabase_admin.table("memoir")\
        .select("id, subject_name, subject_born_on, subject_died_on, subject_is_living, description, status")\
        .eq("id", memoir_id)\
        .maybe_single()\
        .execute()
    memoir = memoir_res.data if memoir_res else None

    if not memoir:
        return None

    # 2. Chapters ordered by sort_order
    chapters_res = supabase_admin.table("chapter")\
        .select("id, title, sort_order")\
        .eq("memoir_id", memoir_id)\
        .order("sort_order")\
        .execute()
    chapters = chapters_res.data or []

    # 3. Memories with media assets via junction table (joined in Python:
    # no FK embed in schema cache, see PGRST200).
    from src.integrations.media_join import attach_media_assets
    memories_res = supabase_admin.table("memory")\
        .select(
            "id, title, body_text, occurred_start, created_at, "
            "chapter_id, position_in_chapter, author_participant_id"
        )\
        .eq("memoir_id", memoir_id)\
        .is_("deleted_at", "null")\
        .order("position_in_chapter")\
        .execute()
    memories = attach_media_assets(memories_res.data or [], memoir_id)

    # 4. Transcripts for audio assets
    transcripts_res = supabase_admin.table("transcript")\
        .select("media_asset_id, display_text, confidence")\
        .eq("memoir_id", memoir_id)\
        .execute()
    transcripts = transcripts_res.data or []

    # 5. Participants for author name resolution
    participants_res = supabase_admin.table("memoir_participant")\
        .select("id, display_name")\
        .eq("memoir_id", memoir_id)\
        .execute()
    participants = participants_res.data or []

    # 6. All photo media assets for the hero carousel and gallery
    photos_res = supabase_admin.table("media_asset")\
        .select("id, storage_key, caption, kind")\
        .eq("memoir_id", memoir_id)\
        .eq("kind", "photo")\
        .execute()
    photos = photos_res.data or []

    return {
        "memoir": memoir,
        "chapters": chapters,
        "memories": memories,
        "transcripts": transcripts,
        "participants": participants,
        "photos": photos,
    }

def fetch_user_active_memoir(user_id: str):
    """
    Fetches the primary active memoir for a user via memoir_participant.
    Joined in Python (no FK embed in schema cache, see PGRST200).
    """
    res = supabase_admin.table("memoir_participant")\
        .select("memoir_id, role")\
        .eq("user_id", user_id)\
        .is_("removed_at", "null")\
        .order("created_at", desc=True)\
        .limit(1)\
        .execute()

    if not res.data:
        return None
    memoir_id = res.data[0].get("memoir_id")
    mem = supabase_admin.table("memoir").select("*").eq("id", memoir_id).execute()
    return mem.data[0] if mem.data else None


def fetch_user_memoirs(user_id: str):
    """
    Fetches every memoir the user owns via memoir_participant.
    Contributors are on hold: only owner rows are returned.
    Joined in Python (no FK embed in schema cache, see PGRST200).
    """
    res = supabase_admin.table("memoir_participant")\
        .select("memoir_id, role, created_at")\
        .eq("user_id", user_id)\
        .eq("role", "owner")\
        .is_("removed_at", "null")\
        .order("created_at", desc=True)\
        .execute()

    if not res.data:
        return []

    memoir_ids = [row.get("memoir_id") for row in res.data]
    mem = supabase_admin.table("memoir").select("*").in_("id", memoir_ids).execute()
    by_id = {row["id"]: row for row in (mem.data or [])}
    # Preserve participant order (newest first); skip rows whose memoir vanished.
    return [by_id[mid] for mid in memoir_ids if mid in by_id]


def fetch_memoir_record(memoir_id: str):
    """Single memoir row by id (None when missing)."""
    res = supabase_admin.table("memoir").select("*").eq("id", memoir_id).execute()
    return res.data[0] if res.data else None


def update_memoir_publication(memoir_id: str, publish: bool):
    """Flips memoir status/published_at for go-live (publish) or take-down."""
    values = {
        "status": "published" if publish else "draft",
        "published_at": datetime.now(timezone.utc).isoformat() if publish else None,
    }
    res = supabase_admin.table("memoir").update(values).eq("id", memoir_id).execute()
    return res.data[0] if res.data else None


def update_memoir_settings(memoir_id: str, fields: dict):
    """Owner-controlled publication settings (comment policy, visibility)."""
    res = supabase_admin.table("memoir").update(fields).eq("id", memoir_id).execute()
    return res.data[0] if res.data else None


def fetch_chapters_for_memoir(memoir_id: str):
    res = supabase_admin.table("chapter").select("*") \
        .eq("memoir_id", memoir_id).order("sort_order", desc=False).execute()
    return res.data or []


def fetch_memories_with_media(memoir_id: str):
    from src.integrations.media_join import attach_media_assets
    res = supabase_admin.table("memory") \
        .select("*") \
        .eq("memoir_id", memoir_id).is_("deleted_at", "null") \
        .order("occurred_start", desc=False).order("created_at", desc=False).execute()
    res.data = attach_media_assets(res.data or [], memoir_id)
    return res.data or []


def fetch_transcripts_for_memoir(memoir_id: str):
    res = supabase_admin.table("transcript").select("*") \
        .eq("memoir_id", memoir_id).execute()
    return res.data or []