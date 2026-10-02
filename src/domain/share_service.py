from datetime import datetime, timezone
import secrets
from typing import Dict, Any, Optional
from fastapi import HTTPException, status
from src.core.config import settings
from src.integrations.share_repository import ShareRepository
from src.integrations.export_repository import ExportRepository
from src.domain.export_service import ExportService
from src.integrations import storage_adapter
from src.schemas.share import ShareLinkResponse


def attach_playback_urls(memories: list) -> None:
    """Same public-URL builder the owner live view uses — the reader has no
    backend-signed fallback, so shared assets must carry their URL inline."""
    for mem in memories or []:
        for link in (mem.get("memory_media") or []):
            asset = link.get("media_asset") if isinstance(link, dict) else None
            if not asset or asset.get("playback_url"):
                continue
            key = asset.get("storage_key")
            try:
                asset["playback_url"] = storage_adapter.create_playback_url(key) if key else None
            except Exception:
                asset["playback_url"] = None

def to_link_response(link: Dict[str, Any]) -> ShareLinkResponse:
    return ShareLinkResponse(
        id=str(link["id"]),
        memoir_id=str(link["memoir_id"]),
        scope=link["scope"],
        token=link["token"],
        url=f"{settings.share_link_base_url.rstrip('/')}/{link['token']}",
        created_by_participant_id=str(link["created_by_participant_id"]) if link.get("created_by_participant_id") else None,
        created_at=link["created_at"],
        expires_at=link.get("expires_at"),
        revoked_at=link.get("revoked_at"),
        open_count=link.get("open_count", 0)
    )

class ShareService:
    
    @staticmethod
    async def create_or_get_share_link(memoir_id: str, user_id: str, scope: str = "view"):
        participant = await ShareRepository.get_participant(memoir_id, user_id)
        if not participant or participant.get("role") != "owner":
            raise HTTPException(status_code=403, detail="Only owners can create share links.")

        memoir = await ShareRepository.get_memoir_by_id(memoir_id)
        if not memoir or memoir.get("status") != "published":
            raise HTTPException(status_code=409, detail="Publish this memoir before sharing it.")

        existing = await ShareRepository.get_active_link(memoir_id, scope)
        if existing:
            return existing

        # No DB default generates the token (staging proved it with a 23502
        # not-null violation), so mint it here: 256-bit, URL-safe, unguessable.
        # open_count likewise has no default — start at zero.
        insert_data = {
            "memoir_id": memoir_id,
            "scope": scope,
            "token": secrets.token_urlsafe(32),
            "open_count": 0,
            "created_by_participant_id": participant["id"]
        }
        return await ShareRepository.insert_link(insert_data)

    @staticmethod
    async def update_share_link(memoir_id: str, user_id: str, payload, scope: str = "view"):
        participant = await ShareRepository.get_participant(memoir_id, user_id)
        if not participant or participant.get("role") != "owner":
            raise HTTPException(status_code=403, detail="Only owners can update links.")
        
        link = await ShareRepository.get_active_link(memoir_id, scope)
        if not link:
            raise HTTPException(status_code=404, detail="No active share link.")

        update_data = {}
        if payload.expires_at is not None:
            update_data["expires_at"] = payload.expires_at.isoformat()

        if not update_data:
            return link
            
        return await ShareRepository.update_link(link["id"], update_data)

    @staticmethod
    async def revoke_share_link(memoir_id: str, user_id: str, scope: str = "view"):
        participant = await ShareRepository.get_participant(memoir_id, user_id)
        if not participant or participant.get("role") != "owner":
            raise HTTPException(status_code=403, detail="Only owners can revoke links.")
            
        link = await ShareRepository.get_active_link(memoir_id, scope)
        if not link:
            raise HTTPException(status_code=404, detail="No active share link.")

        await ShareRepository.update_link(link["id"], {"revoked_at": datetime.now(timezone.utc).isoformat()})

    @staticmethod
    async def read_shared_memoir(token: str) -> dict:
        link = await ShareRepository.get_link_by_token(token)

        if not link or link.get("revoked_at"):
            raise HTTPException(status_code=404, detail="Not found.")

        if link.get("expires_at"):
            expires_at = datetime.fromisoformat(link["expires_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > expires_at:
                raise HTTPException(status_code=404, detail="Link expired.")

        memoir = await ShareRepository.get_memoir_by_id(link["memoir_id"])
        if not memoir or memoir.get("status") != "published":
            raise HTTPException(status_code=404, detail="Not found.")

        await ShareRepository.increment_open_count(link["id"], link.get("open_count", 0))

        memories = await ShareRepository.get_shared_memoir_view(link["memoir_id"])
        attach_playback_urls(memories)
        chapters = await ShareRepository.get_memoir_chapters(link["memoir_id"])

        return {
            **memoir,
            "can_comment": memoir.get("comment_policy") == "anyone_who_can_view",
            "memories": memories,
            "chapters": chapters,
        }

    @staticmethod
    async def join_reader(token: str, display_name: str) -> dict:
        """Validates the live link, then gets-or-creates the named reader row."""
        name = (display_name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Please enter your name.")
        shared = await ShareService.read_shared_memoir(token)
        memoir_id = str(shared["id"])
        reader = await ShareRepository.get_or_create_reader(memoir_id, name)
        return {
            "participant_id": str(reader["id"]),
            "display_name": reader["display_name"],
            "memoir_id": memoir_id,
        }

    @staticmethod
    async def _live_memoir(token: str) -> dict:
        """Lightweight live-link validation for high-frequency reader endpoints.

        Full read_shared_memoir loads every memory/asset/chapter and bumps the
        open counter — far too heavy per heart-click or per-memory comment
        fetch, and a heart should not count as an "open". This checks link
        validity + publication only (2 cheap queries, no writes).
        """
        link = await ShareRepository.get_link_by_token(token)
        if not link or link.get("revoked_at"):
            raise HTTPException(status_code=404, detail="Not found.")
        if link.get("expires_at"):
            expires_at = datetime.fromisoformat(link["expires_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > expires_at:
                raise HTTPException(status_code=404, detail="Link expired.")
        memoir = await ShareRepository.get_memoir_by_id(link["memoir_id"])
        if not memoir or memoir.get("status") != "published":
            raise HTTPException(status_code=404, detail="Not found.")
        return memoir

    @staticmethod
    async def post_guest_comment(token: str, payload: dict) -> dict:
        memoir = await ShareService._live_memoir(token)
        if memoir.get("comment_policy") != "anyone_who_can_view":
            raise HTTPException(status_code=403, detail="Comments are not open on this memoir.")
        memoir_id = str(memoir["id"])

        reader = await ShareRepository.get_reader_participant(
            str(payload.get("participant_id") or ""), memoir_id
        )
        if not reader:
            raise HTTPException(status_code=403, detail="Reader session not recognised.")

        memory_id = payload.get("memory_id")
        if memory_id and not await ShareRepository.get_memory_by_id(str(memory_id), memoir_id):
            raise HTTPException(status_code=404, detail="Memory not found in this memoir.")

        parent_id = payload.get("parent_comment_id")
        if parent_id:
            parent = await ShareRepository.get_comment_by_id(str(parent_id))
            if not parent or str(parent.get("memoir_id")) != memoir_id or parent.get("deleted_at"):
                raise HTTPException(status_code=404, detail="Comment to reply to was not found.")

        body = (payload.get("body") or "").strip()
        if not body:
            raise HTTPException(status_code=400, detail="Comment text cannot be empty.")

        row = await ShareRepository.insert_guest_comment(
            memoir_id, str(reader["id"]), body,
            str(memory_id) if memory_id else None,
            str(parent_id) if parent_id else None,
        )
        return {**row, "author_name": reader["display_name"]}

    @staticmethod
    async def list_guest_comments(token: str, memory_id: Optional[str] = None) -> list:
        memoir = await ShareService._live_memoir(token)
        return await ShareRepository.get_visible_guest_comments(str(memoir["id"]), memory_id)

    @staticmethod
    async def post_reaction(token: str, payload: dict) -> dict:
        memoir = await ShareService._live_memoir(token)
        memoir_id = str(memoir["id"])
        reader = await ShareRepository.get_reader_participant(
            str(payload.get("participant_id") or ""), memoir_id
        )
        if not reader:
            raise HTTPException(status_code=403, detail="Reader session not recognised.")

        memory_id = payload.get("memory_id")
        media_id = payload.get("media_asset_id")
        comment_id = payload.get("comment_id")
        targets = [bool(memory_id), bool(media_id), bool(comment_id)]
        if sum(targets) != 1:
            raise HTTPException(status_code=400, detail="React to exactly one target.")
        kind = str(payload.get("kind") or "i_remember_this_too")

        try:
            if memory_id:
                if not await ShareRepository.get_memory_by_id(str(memory_id), memoir_id):
                    raise HTTPException(status_code=404, detail="Memory not found in this memoir.")
                return await ShareRepository.toggle_memory_media_reaction(
                    memoir_id, str(reader["id"]), memory_id=str(memory_id), kind=kind)
            if media_id:
                if not await ShareRepository.get_media_by_id(str(media_id), memoir_id):
                    raise HTTPException(status_code=404, detail="Media not found in this memoir.")
                return await ShareRepository.toggle_memory_media_reaction(
                    memoir_id, str(reader["id"]), media_asset_id=str(media_id), kind=kind)
            parent = await ShareRepository.get_comment_by_id(str(comment_id))
            if not parent or str(parent.get("memoir_id")) != memoir_id or parent.get("deleted_at"):
                raise HTTPException(status_code=404, detail="Comment not found in this memoir.")
            return await ShareRepository.toggle_comment_reaction(
                memoir_id, str(reader["id"]), str(comment_id), kind)
        except HTTPException:
            raise
        except RuntimeError as e:
            raise HTTPException(status_code=501, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Could not save reaction: {e}")

    @staticmethod
    async def get_reactions(token: str, participant_id: Optional[str] = None) -> dict:
        memoir = await ShareService._live_memoir(token)
        return await ShareRepository.get_reaction_summary(str(memoir["id"]), participant_id)

    @staticmethod
    async def initiate_reader_export(token: str, participant_id: str, background_tasks=None) -> dict:
        """Reader PDF export (images + text only) for the single live link.

        Validates the live token (link not revoked/expired, memoir published)
        plus the joined reader session, then reuses the owner export pipeline:
        the payload builder strictly excludes comments/reactions, so the PDF
        holds only memory text and photos from the live memoir.
        """
        memoir = await ShareService._live_memoir(token)
        memoir_id = str(memoir["id"])
        reader = await ShareRepository.get_reader_participant(
            str(participant_id or ""), memoir_id
        )
        if not reader:
            raise HTTPException(status_code=403, detail="Reader session not recognised.")
        job = ExportRepository.create_export_job(memoir_id, str(reader["id"]), kind="pdf")
        if background_tasks is not None:
            background_tasks.add_task(
                ExportService.process_export_background,
                export_id=job["id"],
                memoir_id=memoir_id,
            )
        return {
            "export_id": job["id"],
            "memoir_id": memoir_id,
            "status": "queued",
            "message": "Export job queued successfully. Processing in background.",
            "created_at": job.get("created_at"),
        }

    @staticmethod
    async def get_reader_export_status(token: str) -> dict:
        """Latest reader-visible export status + signed download URL if ready."""
        memoir = await ShareService._live_memoir(token)
        job = ExportRepository.get_latest_export(str(memoir["id"]))
        if not job:
            return {"status": "none"}
        download_url = None
        if job.get("status") == "ready" and job.get("storage_key"):
            download_url = ExportRepository.get_signed_download_url(job["storage_key"])
        return {
            "success": True,
            "status": job.get("status"),
            "error_message": job.get("error_message"),
            "download_url": download_url,
        }