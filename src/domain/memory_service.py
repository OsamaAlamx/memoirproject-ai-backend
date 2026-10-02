"""
@file memory_service.py
@description Core business logic service managing memory creation with strict
date timeline normalization, media asset linking, feed retrieval, and lifecycle security,
fully decoupled from direct database infrastructure calls.
"""

from fastapi import HTTPException, status
from src.schemas.memory import MemoryCreateRequest
from src.integrations import memory_repository
from src.integrations import memoir_repository
from src.domain.authorization import verify_active_participant
from src.integrations import storage_adapter
from src.domain.transcription_service import transcribe_and_store_audio


def _ensure_memoir_editable(memoir_id: str) -> None:
    """Published memoirs are frozen: no new memories, edits, or deletes.

    The live link serves a fixed book, so owner writes must stop with a
    clear 403 instead of mutating the published archive.
    """
    memoir = memoir_repository.fetch_memoir_record(str(memoir_id))
    if memoir and memoir.get("status") == "published":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Memoir is published and no longer accepts new memories or edits. "
            "Unpublish it to make changes.",
        )


class MemoryService:

    @classmethod
    def create_memory(cls, payload: MemoryCreateRequest, user_session) -> dict:
        user_id = user_session.get("user_id") if isinstance(user_session, dict) else user_session

        participant = verify_active_participant(
            str(payload.memoir_id),
            user_id,
            required_roles=["owner", "admin", "contributor"]
        )
        participant_id = participant["id"]

        _ensure_memoir_editable(str(payload.memoir_id))

        memory_data = {
            "memoir_id": str(payload.memoir_id),
            "author_participant_id": participant_id,
            "title": payload.title,
            "body_text": payload.body_text,
            "status": payload.status,
            "occurred_start": payload.occurred_start.isoformat() if payload.occurred_start else None,
            "occurred_end": payload.occurred_end.isoformat() if payload.occurred_end else None,
            "occurred_precision": payload.occurred_precision,
            "date_source": payload.date_source,
        }

        try:
            mem_res = memory_repository.insert_memory(memory_data)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error while creating memory: {str(e)}"
            )

        if not mem_res or not mem_res.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create memory record."
            )

        new_memory = mem_res.data[0]
        memory_id = new_memory["id"]

        if payload.media_asset_ids:
            owned_assets = memory_repository.verify_media_assets_belong_to_memoir(
                payload.memoir_id, payload.media_asset_ids
            )

            if len(owned_assets) != len(payload.media_asset_ids):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="One or more media assets do not belong to this memoir container."
                )

            link_records = [
                {
                    "memory_id": str(memory_id),
                    "media_asset_id": str(media_id),
                    "memoir_id": str(payload.memoir_id)
                }
                for media_id in payload.media_asset_ids
            ]

            try:
                memory_repository.insert_memory_media(link_records)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to link media assets to memory: {str(e)}"
                )

            for media_id in payload.media_asset_ids:
                asset_record = memory_repository.fetch_media_asset_record(str(media_id))
                if asset_record and asset_record.get("kind") == "audio":
                    storage_key = asset_record.get("storage_key")
                    if storage_key:
                        try:
                            transcribe_and_store_audio(
                                media_asset_id=str(media_id),
                                memoir_id=str(payload.memoir_id),
                                storage_key=storage_key
                            )
                        except Exception:
                            pass

        return new_memory

    @classmethod
    def get_memoir_feed(cls, memoir_id: str, user_id: str, limit: int = 20, offset: int = 0) -> list:
        verify_active_participant(str(memoir_id), str(user_id))

        try:
            res = memory_repository.fetch_memoir_feed_records(str(memoir_id), limit, offset)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch memoir feed: {str(e)}"
            )

        memories = res.data if res and res.data else []

        hydrated_memories = []
        for mem in memories:
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
                        asset_id = asset.get("id")
                        try:
                            asset["transcript"] = memory_repository.fetch_transcript_by_asset(asset_id)
                        except Exception:
                            asset["transcript"] = None
                    else:
                        asset["transcript"] = None

                    media_list.append(asset)

            mem["media_assets"] = media_list
            hydrated_memories.append(mem)

        return hydrated_memories

    @classmethod
    def update_memory(cls, memory_id: str, user_id: str, update_data: dict) -> dict:
        """
        Updates a memory (title/body/date/media) with permission checks.
        Only owners/admins or the memory's author can edit; saved memories are locked.
        """
        mem_res = memory_repository.fetch_memory_row(memory_id)
        if not mem_res.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")

        row = mem_res.data[0]
        memoir_id = row["memoir_id"]

        _ensure_memoir_editable(memoir_id)

        participant_res = memory_repository.fetch_participant(memoir_id, user_id)
        if not participant_res.data:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant of this memoir.")

        participant = participant_res.data[0]
        user_role = participant.get("role")
        participant_id = participant.get("id")

        is_owner_or_admin = user_role in ["owner", "admin"]
        is_author = row.get("author_participant_id") == participant_id
        if not (is_owner_or_admin or is_author):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission to edit this memory.")

        if row.get("status") == "saved":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot edit a finalized memory.")

        # Handle Media Asset Detachments
        to_remove = update_data.get("media_asset_ids_to_remove", [])
        if to_remove:
            memory_repository.remove_memory_media(memory_id, memoir_id, to_remove)

        # Handle Media Asset Attachments
        to_add = update_data.get("media_asset_ids_to_add", [])
        if to_add:
            owned_assets = memory_repository.verify_media_assets_belong_to_memoir(memoir_id, to_add)
            if len(owned_assets) != len(to_add):
                raise HTTPException(status_code=403, detail="Some assets do not belong to this memoir.")
            link_records = [
                {"memory_id": str(memory_id), "media_asset_id": str(media_id), "memoir_id": str(memoir_id)}
                for media_id in to_add
            ]
            memory_repository.insert_memory_media(link_records)
            
            # Automatically transcribe any newly attached audio
            for media_id in to_add:
                asset_record = memory_repository.fetch_media_asset_record(str(media_id))
                if asset_record and asset_record.get("kind") == "audio":
                    storage_key = asset_record.get("storage_key")
                    if storage_key:
                        try:
                            transcribe_and_store_audio(str(media_id), memoir_id, storage_key)
                        except Exception:
                            pass

        # Handle Standard Fields
        allowed_fields = {"title", "body_text", "occurred_start"}
        clean_update = {k: v for k, v in update_data.items() if k in allowed_fields}

        if not clean_update:
            return {"success": True, "data": row}

        # Normalize empty date strings to None so Postgres accepts them
        if "occurred_start" in clean_update and not clean_update["occurred_start"]:
            clean_update["occurred_start"] = None

        # Pydantic v2 model_dump() returns native date/UUID objects, which
        # json.dumps cannot serialize (supabase-py sends them as JSON).
        # Normalize to ISO strings like the create path does.
        from datetime import date as _date, datetime as _datetime
        from uuid import UUID as _UUID
        for _k, _v in list(clean_update.items()):
            if isinstance(_v, (_date, _datetime)):
                clean_update[_k] = _v.isoformat()
            elif isinstance(_v, _UUID):
                clean_update[_k] = str(_v)

        try:
            res = memory_repository.update_memory_record(memory_id, memoir_id, clean_update)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update memory: {str(e)}"
            )

        return {"success": True, "data": res.data[0] if res.data else {}}

    @classmethod
    def delete_memory_by_id(cls, memory_id: str, user_id: str) -> dict:
        mem_res = memory_repository.fetch_memory_row(memory_id)
        if not mem_res.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")
        memoir_id = mem_res.data[0]["memoir_id"]
        return cls.delete_memory(memoir_id, memory_id, user_id)

    @classmethod
    def delete_memory(cls, memoir_id: str, memory_id: str, user_id: str) -> dict:
        _ensure_memoir_editable(memoir_id)
        participant_res = memory_repository.fetch_participant(memoir_id, user_id)
        if not participant_res.data:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a participant of this memoir."
            )

        participant = participant_res.data[0]
        user_role = participant.get("role")
        participant_id = participant.get("id")

        try:
            mem_res = memory_repository.fetch_memory_by_id(memory_id, memoir_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        if not mem_res.data:
            raise HTTPException(status_code=404, detail="Memory not found in this memoir.")

        memory = mem_res.data[0]

        is_owner_or_admin = user_role in ["owner", "admin"]
        is_author = memory.get("author_participant_id") == participant_id

        if not (is_owner_or_admin or is_author):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete this memory."
            )

        if memory.get("status") == "saved":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete a saved/finalized memory."
            )

        try:
            memory_repository.soft_delete_memory_record(memory_id, memoir_id, participant_id)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete memory: {str(e)}"
            )

        return {"success": True, "message": "Memory successfully deleted."}