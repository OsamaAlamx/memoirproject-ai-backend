"""
@file memoir_service.py
@description Business logic and orchestration service for creating memoir containers, 
normalizing subject dates, automatically registering creator as owner participant,
and retrieving live memoir records with signed media URLs and audio transcripts.
"""

from fastapi import HTTPException, status
from src.integrations import memoir_repository
from src.integrations import storage_adapter
from src.domain.authorization import verify_active_participant
from src.schemas.memoir import MemoirCreateRequest


class MemoirService:

    @staticmethod
    def get_user_active_memoir(user_id: str) -> dict | None:
        return memoir_repository.fetch_user_active_memoir(str(user_id))

    @staticmethod
    def list_user_memoirs(user_id: str) -> list[dict]:
        return memoir_repository.fetch_user_memoirs(str(user_id))

    @staticmethod
    def set_memoir_publication(memoir_id: str, user_id: str, publish: bool) -> dict:
        """
        Go-live switch, owner-only. Publishing flips status/published_at so the
        share link starts serving; unpublishing returns it to draft, which
        makes every share token 404. Drafts never serve, even with a live link.
        """
        verify_active_participant(str(memoir_id), str(user_id), required_roles=["owner"])

        memoir = memoir_repository.fetch_memoir_record(memoir_id)
        if not memoir:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Memoir not found."
            )

        try:
            updated = memoir_repository.update_memoir_publication(memoir_id, publish)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error while updating publication: {str(e)}"
            )
        return {"id": memoir_id, "status": updated["status"] if updated else None}

    @staticmethod
    def set_memoir_settings(memoir_id: str, user_id: str, fields: dict) -> dict:
        """Owner-only publication settings (comment policy, visibility)."""
        verify_active_participant(str(memoir_id), str(user_id), required_roles=["owner"])

        memoir = memoir_repository.fetch_memoir_record(memoir_id)
        if not memoir:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Memoir not found."
            )

        allowed = {"comment_policy", "visibility"}
        values = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not values:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nothing to update."
            )
        try:
            updated = memoir_repository.update_memoir_settings(memoir_id, values)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error while updating settings: {str(e)}"
            )
        return {
            "id": memoir_id,
            "status": updated.get("status") if updated else None,
            "comment_policy": updated.get("comment_policy") if updated else None,
            "visibility": updated.get("visibility") if updated else None,
        }

    @staticmethod
    def delete_memoir(memoir_id: str, user_id: str) -> dict:
        """
        Deletes a memoir owned by the user. Owner-only: contributors are on
        hold and readers arrive via share links, so only the owner row counts.
        The schema cascades every child table off the memoir row, so a single
        row delete removes participants, chapters, memories, media, comments,
        exports and notifications with it.
        """
        verify_active_participant(str(memoir_id), str(user_id), required_roles=["owner"])

        memoir = memoir_repository.fetch_memoir_record(memoir_id)
        if not memoir:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Memoir not found."
            )

        try:
            memoir_repository.delete_memoir_record(memoir_id)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error while deleting memoir: {str(e)}"
            )
        return {"id": memoir_id}

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
        if not user_record:
            # Self-heal pre-fix accounts (signed up before profile sync existed).
            from src.integrations import auth_repository
            try:
                auth_repository.ensure_user_account(
                    user_id,
                    user_session.get("email") or "",
                    (user_session.get("full_name") or user_session.get("email") or "Memoir Owner"),
                )
                user_res = memoir_repository.fetch_user_account(user_id)
                user_record = user_res.data[0] if user_res and user_res.data else {}
            except Exception:
                pass
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

        memoir = memoir_repository.fetch_memoir_record(memoir_id)
        if not memoir:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Memoir container not found."
            )

        chapters = memoir_repository.fetch_chapters_for_memoir(memoir_id)

        memories_raw = memoir_repository.fetch_memories_with_media(memoir_id)

        # Batch-fetch transcripts for all audio assets in this memoir
        transcripts = memoir_repository.fetch_transcripts_for_memoir(memoir_id)
        t_map = {str(t["media_asset_id"]): t for t in (transcripts or [])}

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