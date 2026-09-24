"""
@file memoir_service.py
@description Business logic and orchestration service for creating memoir containers, 
normalizing subject dates, automatically registering creator as owner participant,
and retrieving live memoir records with signed media URLs and audio transcripts.
"""

from fastapi import HTTPException, status
from src.integrations import memoir_repository
from src.integrations import storage_adapter
from src.integrations.supabase_client import supabase_admin
from src.domain.authorization import verify_active_participant
from src.schemas.memoir import MemoirCreateRequest


class MemoirService:

    @staticmethod
    def create_memoir(payload: MemoirCreateRequest, user_session: dict) -> dict:
        user_id = user_session.get("user_id")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User session is missing user ID."
            )

        try:
            user_res = memoir_repository.fetch_user_account(user_id)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch user account details: {str(e)}"
            )

        user_record = user_res.data[0] if user_res and user_res.data else {}
        display_name = user_record.get("full_name") or "Memoir Owner"
        user_email = user_record.get("email")

        memoir_data = {
            "subject_name": payload.subject_name,
            "subject_born_on": str(payload.subject_born_on) if payload.subject_born_on else None,
            "subject_died_on": str(payload.subject_died_on) if payload.subject_died_on else None,
            "subject_is_living": payload.subject_is_living,
            "description": payload.description,
            "visibility": payload.visibility,
            "comment_policy": payload.comment_policy,
            "created_by_user_id": user_id,
            "status": "draft"
        }

        try:
            db_response = memoir_repository.insert_memoir(memoir_data)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Database error while creating memoir: {str(e)}")

        created_memoir = db_response.data[0]
        memoir_id = created_memoir["id"]

        participant_data = {
            "memoir_id": memoir_id,
            "user_id": user_id,
            "role": "owner",
            "display_name": display_name,
            "email": user_email,
            "relationship": payload.relationship
        }

        try:
            memoir_repository.insert_memoir_participant(participant_data)
        except Exception as e:
            try:
                memoir_repository.delete_memoir_record(memoir_id)
            except Exception:
                pass
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to register memoir owner. Operation rolled back: {str(e)}"
            )
            
        return created_memoir

    @classmethod
    def get_live_memoir(cls, memoir_id: str, user_id: str) -> dict:
        """
        Verifies participant authorization and returns the full live memoir details
        including metadata, chapters, memories with signed playback URLs, and audio transcripts.
        """
        verify_active_participant(str(memoir_id), str(user_id))

        memoir_res = supabase_admin.table("memoir").select("*").eq("id", memoir_id).execute()
        if not memoir_res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Memoir container not found."
            )

        memoir = memoir_res.data[0]

        chapters_res = (
            supabase_admin.table("chapter")
            .select("*")
            .eq("memoir_id", memoir_id)
            .order("sort_order", desc=False)
            .execute()
        )
        chapters = chapters_res.data or []

        memories_res = (
            supabase_admin.table("memory")
            .select("*, memory_media(*, media_asset(*))")
            .eq("memoir_id", memoir_id)
            .is_("deleted_at", "null")
            .order("occurred_start", desc=False)
            .order("created_at", desc=False)
            .execute()
        )
        memories_raw = memories_res.data or []

        # Batch-fetch transcripts for all audio assets in this memoir
        transcripts_res = (
            supabase_admin.table("transcript")
            .select("*")
            .eq("memoir_id", memoir_id)
            .execute()
        )
        t_map = {str(t["media_asset_id"]): t for t in (transcripts_res.data or [])}

        hydrated_memories = []
        for mem in memories_raw:
            media_list = []
            raw_links = mem.pop("memory_media", [])
            for link in raw_links:
                asset = link.get("media_asset")
                if asset:
                    storage_key = asset.get("storage_key")
                    playback_url = None
                    if storage_key:
                        try:
                            playback_url = storage_adapter.create_playback_url(storage_key)
                        except Exception:
                            playback_url = None
                    asset["playback_url"] = playback_url

                    if asset.get("kind") == "audio":
                        asset["transcript"] = t_map.get(str(asset.get("id")))
                    else:
                        asset["transcript"] = None

                    media_list.append(asset)
            mem["media_assets"] = media_list
            hydrated_memories.append(mem)

        return {
            "memoir": memoir,
            "chapters": chapters,
            "memories": hydrated_memories
        }