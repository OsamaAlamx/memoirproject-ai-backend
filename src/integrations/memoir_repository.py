"""
@file memoir_repository.py
@description Data access layer adapter module handling direct Supabase queries 
and persistence for user accounts, memoirs, and memoir participant roles.
"""

from src.integrations.supabase_client import supabase_admin


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

    # 3. Memories with embedded media assets via junction table
    memories_res = supabase_admin.table("memory")\
        .select(
            "id, title, body_text, occurred_start, created_at, "
            "chapter_id, position_in_chapter, author_participant_id, "
            "memory_media(media_asset(id, kind, storage_key, caption))"
        )\
        .eq("memoir_id", memoir_id)\
        .is_("deleted_at", "null")\
        .order("position_in_chapter")\
        .execute()
    memories = memories_res.data or []

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