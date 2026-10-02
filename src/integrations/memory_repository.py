"""
@file memory_repository.py
@description Data access layer adapter module handling direct Supabase queries
and persistence operations for memories, participant permissions, and media junctions,
enforcing strict multi-tenant memoir_id isolation.
"""

from src.integrations.supabase_client import supabase_admin


def fetch_participant(memoir_id: str, user_id: str):
    return supabase_admin.table("memoir_participant") \
        .select("*") \
        .eq("memoir_id", memoir_id) \
        .eq("user_id", user_id) \
        .is_("removed_at", "null") \
        .execute()


def insert_memory(memory_data: dict):
    return supabase_admin.table("memory").insert(memory_data).execute()


def insert_memory_media(link_records: list):
    return supabase_admin.table("memory_media").insert(link_records).execute()


def remove_memory_media(memory_id: str, memoir_id: str, media_asset_ids: list):
    """Safely detaches specific media assets from a memory."""
    return supabase_admin.table("memory_media") \
        .delete() \
        .eq("memory_id", memory_id) \
        .eq("memoir_id", memoir_id) \
        .in_("media_asset_id", media_asset_ids) \
        .execute()


def fetch_memoir_feed_records(memoir_id: str, limit: int = 20, offset: int = 0):
    from src.integrations.media_join import attach_media_assets
    end_index = offset + limit - 1
    res = supabase_admin.table("memory") \
        .select(
            "id, memoir_id, author_participant_id, title, body_text, status, "
            "occurred_start, occurred_end, occurred_precision, date_source, created_at"
        ) \
        .eq("memoir_id", memoir_id) \
        .is_("deleted_at", "null") \
        .order("created_at", desc=True) \
        .range(offset, end_index) \
        .execute()
    # Join media in Python: no FK embed in schema cache (PGRST200).
    res.data = attach_media_assets(res.data or [], memoir_id)
    return res


def fetch_memory_by_id(memory_id: str, memoir_id: str):
    return supabase_admin.table("memory") \
        .select("memoir_id, status, author_participant_id") \
        .eq("id", memory_id) \
        .eq("memoir_id", memoir_id) \
        .execute()


def fetch_memory_row(memory_id: str):
    return supabase_admin.table("memory") \
        .select("id, memoir_id, status, author_participant_id") \
        .eq("id", memory_id) \
        .execute()


def delete_memory_record(memory_id: str, memoir_id: str):
    return supabase_admin.table("memory") \
        .delete() \
        .eq("id", memory_id) \
        .eq("memoir_id", memoir_id) \
        .execute()


def verify_media_assets_belong_to_memoir(memoir_id: str, media_asset_ids: list[str]):
    res = supabase_admin.table("media_asset") \
        .select("id") \
        .eq("memoir_id", memoir_id) \
        .in_("id", media_asset_ids) \
        .execute()
    return res.data or []


def soft_delete_memory_record(memory_id: str, memoir_id: str, deleted_by_participant_id: str):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    return supabase_admin.table("memory") \
        .update({"deleted_at": now, "deleted_by_participant_id": deleted_by_participant_id}) \
        .eq("id", memory_id) \
        .eq("memoir_id", memoir_id) \
        .execute()


def fetch_media_asset_record(media_asset_id: str):
    res = supabase_admin.table("media_asset") \
        .select("*") \
        .eq("id", media_asset_id) \
        .maybe_single() \
        .execute()
    return res.data if res else None


def upsert_transcript_record(transcript_payload: dict):
    return supabase_admin.table("transcript").upsert(transcript_payload).execute()


def update_memory_record(memory_id: str, memoir_id: str, update_data: dict):
    """
    Updates a memory record with new fields (title, body_text, occurred_start),
    strictly scoped by memoir_id to enforce tenant isolation.
    """
    from datetime import datetime, timezone
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    return supabase_admin.table("memory") \
        .update(update_data) \
        .eq("id", memory_id) \
        .eq("memoir_id", memoir_id) \
        .execute()


def fetch_transcript_by_asset(media_asset_id: str):
    """Single transcript row for an audio asset (None when missing)."""
    res = supabase_admin.table("transcript").select("*") \
        .eq("media_asset_id", media_asset_id).maybe_single().execute()
    return res.data if res and res.data else None