from src.integrations.supabase_client import supabase_admin

def get_memories_for_organization(memoir_id: str):
    res = supabase_admin.table("memory")\
        .select("id, title, body_text, occurred_start, chapter_id, position_in_chapter")\
        .eq("memoir_id", memoir_id)\
        .is_("deleted_at", "null")\
        .execute()
    return res.data or []

def get_existing_chapters(memoir_id: str):
    res = supabase_admin.table("chapter")\
        .select("*")\
        .eq("memoir_id", memoir_id)\
        .execute()
    return res.data or []

def apply_chapters_to_db(memoir_id: str, chapters_payload: list):
    # Step 1: Unlink chapter_id on memories first to avoid composite FK nullifying memory.memoir_id
    supabase_admin.table("memory")\
        .update({"chapter_id": None, "position_in_chapter": None})\
        .eq("memoir_id", memoir_id)\
        .execute()

    # Step 2: Delete old chapters safely
    supabase_admin.table("chapter")\
        .delete()\
        .eq("memoir_id", memoir_id)\
        .execute()

    # Step 3: Insert new chapters and re-link memories
    for idx, chapter in enumerate(chapters_payload):
        ch_res = supabase_admin.table("chapter").insert({
            "memoir_id": memoir_id,
            "title": chapter["title"],
            "summary": chapter.get("summary", ""), # Save the generated biographical text
            "sort_order": idx,
            "created_by": "ai",
            "edited_by_owner": True
        }).execute()
        
        if ch_res.data:
            new_chapter_id = ch_res.data[0]["id"]
            for pos, mem in enumerate(chapter.get("memories", [])):
                supabase_admin.table("memory").update({
                    "chapter_id": new_chapter_id,
                    "position_in_chapter": pos
                }).eq("id", mem["id"]).execute()