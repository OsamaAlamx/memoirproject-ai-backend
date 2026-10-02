"""
@file repositories/comments_repository.py
@description Handles comment queries and secure participant resolution.
"""

from typing import List, Dict, Any
from src.integrations.supabase_client import supabase_admin

class RepositoryError(RuntimeError):
    pass

class NotParticipantError(PermissionError):
    pass

class CommentsRepository:

    @staticmethod
    async def get_comments_by_memory_id(memory_id: str) -> List[Dict[str, Any]]:
        """Fetches raw comments without database embedding to avoid cache sync issues."""
        try:
            response = supabase_admin.table("comment")\
    .select("*")\
    .eq("memory_id", memory_id)\
    .is_("deleted_at", "null")\
    .is_("hidden_at", "null")\
    .order("created_at", desc=False)\
    .execute()

            data = response.data or []
            formatted_comments = []

            for item in data:
                comment_record = {**item}
                comment_record["author_name"] = "Family Member"  # Safe fallback (Just for mock data)
                formatted_comments.append(comment_record)
                
            return formatted_comments

        except Exception as e:
            raise RepositoryError(
                f"Database error while fetching comments: {str(e)}"
            )
                    
    @staticmethod
    async def get_pending_comments(memoir_id: str) -> List[Dict[str, Any]]:
        """Guest comments awaiting owner approval (hidden, not withdrawn)."""
        try:
            response = supabase_admin.table("comment")\
                .select("*")\
                .eq("memoir_id", memoir_id)\
                .is_("deleted_at", "null")\
                .not_.is_("hidden_at", "null")\
                .order("created_at", desc=False)\
                .execute()
            rows = response.data or []
            author_ids = list({r.get("author_participant_id") for r in rows if r.get("author_participant_id")})
            names: Dict[str, str] = {}
            if author_ids:
                pres = supabase_admin.table("memoir_participant")\
                    .select("id, display_name")\
                    .in_("id", author_ids)\
                    .execute()
                names = {p["id"]: p.get("display_name", "Reader") for p in (pres.data or [])}
            out = []
            for item in rows:
                record = {**item}
                record["author_name"] = names.get(item.get("author_participant_id"), "Reader")
                out.append(record)
            return out
        except Exception as e:
            raise RepositoryError(f"Database error while fetching pending comments: {str(e)}")

    @staticmethod
    async def approve_comment(comment_id: str) -> Dict[str, Any]:
        try:
            res = supabase_admin.table("comment")\
                .update({"hidden_at": None, "hidden_by_participant_id": None})\
                .eq("id", comment_id)\
                .execute()
            if not res.data:
                raise RepositoryError("Comment not found.")
            row = res.data[0]
            author_name = "Reader"
            if row.get("author_participant_id"):
                pres = supabase_admin.table("memoir_participant")\
                    .select("display_name")\
                    .eq("id", row["author_participant_id"])\
                    .execute()
                if pres.data:
                    author_name = pres.data[0].get("display_name", "Reader")
            return {**row, "author_name": author_name}
        except RepositoryError:
            raise
        except Exception as e:
            raise RepositoryError(f"Database error while approving comment: {str(e)}")

    @staticmethod
    async def delete_comment_hard(comment_id: str) -> Dict[str, Any]:
        """Owner reject: permanent row delete (replies cascade per schema)."""
        try:
            res = supabase_admin.table("comment").delete().eq("id", comment_id).execute()
            if not res.data:
                raise RepositoryError("Comment not found.")
            return {"id": comment_id}
        except RepositoryError:
            raise
        except Exception as e:
            raise RepositoryError(f"Database error while deleting comment: {str(e)}")

    @staticmethod
    async def get_comment_memoir_id(comment_id: str) -> str | None:
        try:
            res = supabase_admin.table("comment").select("memoir_id").eq("id", comment_id).execute()
            return res.data[0]["memoir_id"] if res.data else None
        except Exception as e:
            raise RepositoryError(f"Database error while fetching comment: {str(e)}")

    @staticmethod
    async def get_memory_memoir_id(memory_id: str) -> str | None:
        """Resolve the owning memoir for a memory (authz scoping, no row data)."""
        try:
            res = supabase_admin.table("memory").select("memoir_id").eq("id", memory_id).execute()
            return res.data[0]["memoir_id"] if res.data else None
        except Exception as e:
            raise RepositoryError(f"Database error while fetching memory: {str(e)}")

    @staticmethod
    async def insert_comment(payload: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        """
        Securely resolves the user's memoir_participant_id for the given memoir
        and inserts the comment using standard selection without embedding.
        """
        try:
            memoir_id = str(payload["memoir_id"])

            # 1. Look up the memoir_participant record for this user in this memoir
            # Filter removed participants: revoked access cannot post.
            participant_res = supabase_admin.table("memoir_participant")\
                .select("id")\
                .eq("memoir_id", memoir_id)\
                .eq("user_id", user_id)\
                .is_("removed_at", "null")\
                .execute()

            participants = participant_res.data or []
            if not participants:
                raise NotParticipantError(
                    "User is not an authorized participant of this memoir."
                )

            participant_id = participants[0]["id"]

            # 2. Scope-check every referenced target belongs to the same memoir.
            memory_id = str(payload["memory_id"]) if payload.get("memory_id") else None
            media_asset_id = str(payload["media_asset_id"]) if payload.get("media_asset_id") else None
            parent_comment_id = str(payload["parent_comment_id"]) if payload.get("parent_comment_id") else None

            if memory_id:
                mres = supabase_admin.table("memory").select("id")\
                    .eq("id", memory_id).eq("memoir_id", memoir_id).execute()
                if not (mres.data or []):
                    raise RepositoryError("Target memory does not belong to this memoir.")
            if media_asset_id:
                ares = supabase_admin.table("media_asset").select("id")\
                    .eq("id", media_asset_id).eq("memoir_id", memoir_id).execute()
                if not (ares.data or []):
                    raise RepositoryError("Target media does not belong to this memoir.")
            if parent_comment_id:
                cres = supabase_admin.table("comment").select("id")\
                    .eq("id", parent_comment_id).eq("memoir_id", memoir_id).execute()
                if not (cres.data or []):
                    raise RepositoryError("Parent comment does not belong to this memoir.")

            # 2. Insert the comment using the resolved participant ID
            insert_data = {
                "memoir_id": memoir_id,
                "memory_id": memory_id,
                "media_asset_id": media_asset_id,
                "parent_comment_id": parent_comment_id, 
                "author_participant_id": participant_id,
                "body": payload["body"].strip()
            }

            # Insert and select only the comment record itself (no embedded joins)
            # also normalize the insert (drop the non-standard .select() chain after .insert())
            response = supabase_admin.table("comment")\
            .insert(insert_data)\
            .execute()

            data = response.data or []
            if not data:
                raise RepositoryError(
                    "Failed to save comment record."
                )

            # Grab the newly inserted record from Supabase's list response
            inserted_record = data[0]

            result = {**inserted_record}
            result["author_name"] = "Family Member"  # Safe fallback matching your fetch method
            return result

        except (NotParticipantError, RepositoryError):
            raise
        except Exception as e:
            raise RepositoryError(
                f"Error inserting comment: {str(e)}"
            )