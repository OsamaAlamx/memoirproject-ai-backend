"""
@file integrations/export_repository.py
@description Database repository for memoir export job tracking and memoir data retrieval.
"""

from src.integrations.supabase_client import supabase_admin
from src.core.config import settings
from datetime import datetime, timezone

BUCKET_NAME = settings.supabase_media_bucket

class ExportRepository:

    @staticmethod
    def create_export_job(memoir_id: str, participant_id: str, kind: str = "pdf") -> dict:
        """Inserts a new export job with 'queued' status."""
        response = supabase_admin.table("memoir_export").insert({
            "memoir_id": memoir_id,
            "requested_by_participant_id": participant_id,
            "kind": kind,
            "status": "queued"
        }).execute()
        
        if not response.data:
            raise Exception("Failed to create export job record in database.")
        return response.data[0]

    @staticmethod
    def update_job_status(
        export_id: str, 
        status: str, 
        storage_key: str = None, 
        byte_size: int = None, 
        error_message: str = None
    ) -> None:
        """Updates the export job status, storage reference, or failure reason."""
        update_data = {
            "status": status,
            "completed_at": datetime.now(timezone.utc).isoformat() if status in ["ready", "failed"] else None
        }
        if storage_key is not None:
            update_data["storage_key"] = storage_key
        if byte_size is not None:
            update_data["byte_size"] = byte_size
        if error_message is not None:
            update_data["error_message"] = error_message

        supabase_admin.table("memoir_export").update(update_data).eq("id", export_id).execute()

    @staticmethod
    def fetch_memoir_export_payload(memoir_id: str) -> dict:
        """
        Fetches memoir details, memories, media assets, and audio transcripts.
        Strictly excludes comments to ensure export represents a static keepsake archive.
        """
        memoir_res = supabase_admin.table("memoir").select("*").eq("id", memoir_id).single().execute()
        memoir_data = memoir_res.data if memoir_res else {}

        memories_res = (
            supabase_admin.table("memory")
            .select("id, title, body_text, occurred_start, created_at")
            .eq("memoir_id", memoir_id)
            .order("occurred_start", desc=False)
            .execute()
        )
        memories = memories_res.data if memories_res.data else []

        media_res = (
            supabase_admin.table("media_asset")
            .select("id, memoir_id, storage_key, caption, kind")
            .eq("memoir_id", memoir_id)
            .execute()
        )
        media_assets = media_res.data if media_res.data else []

        transcripts_res = (
            supabase_admin.table("transcript")
            .select("media_asset_id, display_text")
            .eq("memoir_id", memoir_id)
            .execute()
        )
        transcripts = transcripts_res.data if transcripts_res.data else []

        return {
            "memoir": memoir_data,
            "memories": memories,
            "media_assets": media_assets,
            "transcripts": transcripts
        }

    @staticmethod
    def upload_pdf_to_storage(storage_key: str, pdf_bytes: bytes) -> None:
        """Uploads generated PDF binary stream to Supabase Storage bucket."""
        supabase_admin.storage.from_(BUCKET_NAME).upload(
            path=storage_key,
            file=pdf_bytes,
            file_options={"content-type": "application/pdf"}
        )

    @staticmethod
    def get_signed_download_url(storage_key: str) -> str:
        """Generates a secure temporary download URL for the exported PDF."""
        res = supabase_admin.storage.from_(BUCKET_NAME).create_signed_url(storage_key, 3600)
        return res.get("signedURL") or res.get("signedUrl")
    
    @staticmethod
    def get_latest_export(memoir_id: str) -> dict:
        res = (
            supabase_admin.table("memoir_export")
            .select("*")
            .eq("memoir_id", memoir_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None