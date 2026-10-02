from typing import Dict, Any, Optional, List
from src.integrations.supabase_client import supabase_admin

class ShareRepository:

    @staticmethod
    async def get_participant(memoir_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Resolves the participant ID and role for the user."""
        try:
            res = supabase_admin.table("memoir_participant")\
                .select("id, role")\
                .eq("memoir_id", memoir_id)\
                .eq("user_id", user_id)\
                .is_("removed_at", None)\
                .execute()
            return res.data[0] if res.data else None
        except Exception as e:
            raise RuntimeError(f"Database error: {str(e)}")

    @staticmethod
    async def get_memoir_by_id(memoir_id: str) -> Optional[Dict[str, Any]]:
        res = supabase_admin.table("memoir").select("*").eq("id", memoir_id).execute()
        return res.data[0] if res.data else None

    @staticmethod
    async def get_active_link(memoir_id: str, scope: str) -> Optional[Dict[str, Any]]:
        """Matches your SQL constraint: one live link per scope per memoir."""
        res = supabase_admin.table("memoir_link")\
            .select("*")\
            .eq("memoir_id", memoir_id)\
            .eq("scope", scope)\
            .is_("revoked_at", None)\
            .execute()
        return res.data[0] if res.data else None

    @staticmethod
    async def get_link_by_token(token: str) -> Optional[Dict[str, Any]]:
        res = supabase_admin.table("memoir_link").select("*").eq("token", token).execute()
        return res.data[0] if res.data else None

    @staticmethod
    async def insert_link(insert_data: Dict[str, Any]) -> Dict[str, Any]:
        # Token and defaults are generated automatically by your Postgres schema.
        # No .select() after .insert(): supabase-py returns the created row
        # directly, and the chained select raises AttributeError (500s share-link creation).
        res = supabase_admin.table("memoir_link").insert(insert_data).execute()
        if not res.data:
            raise RuntimeError("Failed to create share link")
        return res.data[0]

    @staticmethod
    async def update_link(link_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        # Same rule: update().eq().execute() returns the row; no chained select.
        res = supabase_admin.table("memoir_link").update(update_data).eq("id", link_id).execute()
        return res.data[0]

    @staticmethod
    async def increment_open_count(link_id: str, current_count: int) -> None:
        supabase_admin.table("memoir_link").update({"open_count": current_count + 1}).eq("id", link_id).execute()

    @staticmethod
    async def get_shared_memoir_view(memoir_id: str) -> List[Dict[str, Any]]:
        from src.integrations.media_join import attach_media_assets
        res = supabase_admin.table("memory")\
            .select("*")\
            .eq("memoir_id", memoir_id)\
            .is_("deleted_at", None)\
            .order("created_at", desc=True)\
            .execute()
        # No status filter: nothing in the product ever flips memories to
        # 'submitted' (capture saves 'draft'), and the owner's own live view
        # is equally unfiltered — filtering here served only empty books.
        return attach_media_assets(res.data or [], memoir_id)

    @staticmethod
    async def get_memoir_chapters(memoir_id: str) -> List[Dict[str, Any]]:
        res = supabase_admin.table("chapter")\
            .select("id, title, summary, sort_order")\
            .eq("memoir_id", memoir_id)\
            .order("sort_order", desc=False)\
            .execute()
        return res.data or []

    @staticmethod
    async def get_or_create_reader(memoir_id: str, display_name: str) -> Dict[str, Any]:
        """Named guests share one reader row per display name per memoir (unique per link)."""
        name = display_name.strip()
        existing = supabase_admin.table("memoir_participant")\
            .select("id, display_name")\
            .eq("memoir_id", memoir_id)\
            .eq("role", "reader")\
            .eq("display_name", name)\
            .is_("removed_at", None)\
            .execute()
        if existing.data:
            return existing.data[0]
        # memoir_participant.relationship is NOT NULL with no default;
        # guests have no subject relationship, so use the neutral "other".
        created = supabase_admin.table("memoir_participant")\
            .insert({"memoir_id": memoir_id, "role": "reader", "display_name": name, "relationship": "other"})\
            .execute()
        if not created.data:
            raise RuntimeError("Failed to register reader.")
        return created.data[0]

    @staticmethod
    async def get_reader_participant(participant_id: str, memoir_id: str) -> Optional[Dict[str, Any]]:
        res = supabase_admin.table("memoir_participant")\
            .select("id, display_name")\
            .eq("id", participant_id)\
            .eq("memoir_id", memoir_id)\
            .eq("role", "reader")\
            .is_("removed_at", None)\
            .execute()
        return res.data[0] if res.data else None

    @staticmethod
    async def insert_guest_comment(
        memoir_id: str,
        participant_id: str,
        body: str,
        memory_id: Optional[str] = None,
        parent_comment_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Guest comments insert hidden (pending owner approval). hidden_by=self
        satisfies the hide-attribution CHECK; approval clears both columns."""
        from datetime import datetime, timezone
        res = supabase_admin.table("comment")\
            .insert({
                "memoir_id": memoir_id,
                "memory_id": memory_id,
                "media_asset_id": None,
                "parent_comment_id": parent_comment_id,
                "author_participant_id": participant_id,
                "body": body.strip(),
                "hidden_at": datetime.now(timezone.utc).isoformat(),
                "hidden_by_participant_id": participant_id,
            })\
            .execute()
        if not res.data:
            raise RuntimeError("Failed to save comment.")
        return res.data[0]

    @staticmethod
    async def get_visible_guest_comments(memoir_id: str, memory_id: Optional[str] = None) -> List[Dict[str, Any]]:
        q = supabase_admin.table("comment")\
            .select("*")\
            .eq("memoir_id", memoir_id)\
            .is_("deleted_at", None)\
            .is_("hidden_at", None)
        q = q.eq("memory_id", memory_id) if memory_id else q.is_("memory_id", None)
        res = q.order("created_at", desc=False).execute()
        rows = res.data or []
        author_ids = list({r.get("author_participant_id") for r in rows if r.get("author_participant_id")})
        names: Dict[str, str] = {}
        if author_ids:
            pres = supabase_admin.table("memoir_participant")\
                .select("id, display_name")\
                .in_("id", author_ids)\
                .execute()
            names = {p["id"]: p.get("display_name", "Reader") for p in (pres.data or [])}
        return [{**r, "author_name": names.get(r.get("author_participant_id"), "Reader")} for r in rows]

    @staticmethod
    async def get_comment_by_id(comment_id: str) -> Optional[Dict[str, Any]]:
        res = supabase_admin.table("comment").select("*").eq("id", comment_id).execute()
        return res.data[0] if res.data else None

    @staticmethod
    async def get_memory_by_id(memory_id: str, memoir_id: str) -> Optional[Dict[str, Any]]:
        res = supabase_admin.table("memory")\
            .select("id")\
            .eq("id", memory_id)\
            .eq("memoir_id", memoir_id)\
            .is_("deleted_at", None)\
            .execute()
        return res.data[0] if res.data else None

    @staticmethod
    async def get_media_by_id(media_id: str, memoir_id: str) -> Optional[Dict[str, Any]]:
        res = supabase_admin.table("media_asset")\
            .select("id")\
            .eq("id", media_id)\
            .eq("memoir_id", memoir_id)\
            .is_("deleted_at", None)\
            .execute()
        return res.data[0] if res.data else None

    @staticmethod
    async def toggle_memory_media_reaction(
        memoir_id: str,
        participant_id: str,
        memory_id: Optional[str] = None,
        media_asset_id: Optional[str] = None,
        kind: str = "i_remember_this_too",
    ) -> Dict[str, Any]:
        """One reaction of a kind per participant per target; repeat call removes it."""
        existing_q = supabase_admin.table("reaction")\
            .select("id")\
            .eq("memoir_id", memoir_id)\
            .eq("participant_id", participant_id)\
            .eq("kind", kind)
        existing_q = existing_q.eq("memory_id", memory_id) if memory_id else existing_q.is_("memory_id", None)
        existing_q = existing_q.eq("media_asset_id", media_asset_id) if media_asset_id else existing_q.is_("media_asset_id", None)
        existing = existing_q.execute()
        if existing.data:
            supabase_admin.table("reaction").delete().eq("id", existing.data[0]["id"]).execute()
            reacted = False
        else:
            supabase_admin.table("reaction")\
                .insert({
                    "memoir_id": memoir_id,
                    "memory_id": memory_id,
                    "media_asset_id": media_asset_id,
                    "participant_id": participant_id,
                    "kind": kind,
                })\
                .execute()
            reacted = True
        count_res = supabase_admin.table("reaction")\
            .select("id")\
            .eq("memoir_id", memoir_id)\
            .eq("kind", kind)
        count_res = count_res.eq("memory_id", memory_id) if memory_id else count_res.is_("memory_id", None)
        count_res = count_res.eq("media_asset_id", media_asset_id) if media_asset_id else count_res.is_("media_asset_id", None)
        count = len(count_res.execute().data or [])
        return {"reacted": reacted, "count": count}

    @staticmethod
    async def toggle_comment_reaction(
        memoir_id: str,
        participant_id: str,
        comment_id: str,
        kind: str = "i_remember_this_too",
    ) -> Dict[str, Any]:
        """Toggle one comment reaction per participant; repeat call removes it.
        Requires reaction.comment_id (BUG-005 migration on the real database)."""
        try:
            existing = supabase_admin.table("reaction")\
                .select("id")\
                .eq("memoir_id", memoir_id)\
                .eq("participant_id", participant_id)\
                .eq("kind", kind)\
                .eq("comment_id", comment_id)\
                .execute()
            if existing.data:
                supabase_admin.table("reaction").delete().eq("id", existing.data[0]["id"]).execute()
                reacted = False
            else:
                supabase_admin.table("reaction")\
                    .insert({
                        "memoir_id": memoir_id,
                        "memory_id": None,
                        "media_asset_id": None,
                        "comment_id": comment_id,
                        "participant_id": participant_id,
                        "kind": kind,
                    })\
                    .execute()
                reacted = True
            count = len(supabase_admin.table("reaction")\
                .select("id")\
                .eq("memoir_id", memoir_id)\
                .eq("kind", kind)\
                .eq("comment_id", comment_id)\
                .execute().data or [])
            return {"reacted": reacted, "count": count}
        except Exception as e:
            msg = str(e).lower()
            if "reaction_exactly_one_target" in msg or "23514" in msg:
                raise RuntimeError(
                    "reaction table rejected the comment reaction (check constraint). "
                    "Apply the BUG-005 migration: comment_id column + "
                    "CHECK (num_nulls(memory_id, media_asset_id, comment_id) = 2).")
            if "comment_id" in msg and ("column" in msg or "schema" in msg or "pgrst" in msg):
                raise RuntimeError("Comment reactions need the comment_id migration (BUG-005).")
            raise

    @staticmethod
    async def get_reaction_summary(memoir_id: str, participant_id: Optional[str] = None) -> Dict[str, Any]:
        res = supabase_admin.table("reaction")\
            .select("*")\
            .eq("memoir_id", memoir_id)\
            .execute()
        counts: Dict[str, int] = {}
        mine: list[str] = []
        for r in (res.data or []):
            target = r.get("memory_id") or r.get("media_asset_id") or r.get("comment_id")
            if not target:
                continue
            counts[target] = counts.get(target, 0) + 1
            if participant_id and r.get("participant_id") == participant_id:
                mine.append(target)
        return {"counts": counts, "reacted": mine}