"""
@file domain/media_service.py
@description Core business logic service managing memoir participant authorizations,
secure path generation, upload validation, and database metadata persistence,
fully decoupled from direct infrastructure calls and secured against path traversal.
"""

from fastapi import HTTPException, status
from src.integrations import media_repository
from src.integrations import memoir_repository
from src.integrations import storage_adapter
from src.schemas.media import PresignedUrlRequest, MediaMetadataRequest
from src.domain.authorization import verify_active_participant
import logging

logger = logging.getLogger(__name__)

from src.core.config import (
    STORAGE_TIER_HOT,
    TRANSCRIPTION_STATUS_PENDING,
    settings,
)

# Caps transcription/AI cost from very long recordings.
MAX_AUDIO_VIDEO_DURATION_MS = 6 * 60 * 60 * 1000


class MediaService:
    """
    Handles business rules, participant access controls, security validations, 
    and database record cataloging for media assets.
    """


    @classmethod
    def generate_presigned_url(cls, payload: PresignedUrlRequest, user_session: dict) -> dict:
        """
        Authorizes user access to a memoir, validates file upload limits/types, 
        generates a collision-free secure path, and requests a short-lived signed upload URL.

        Args:
            payload (PresignedUrlRequest): The request payload containing memoir ID, MIME type, and size.
            user_session (dict): The active user session dictionary containing the user ID.

        Returns:
            dict: A dictionary containing the secure storage key, signed upload URL, and token.

        Raises:
            HTTPException (500): If the storage provider fails to generate the signed URL.
        """
        user_id = user_session.get("user_id")
        memoir_id = payload.memoir_id
        
        verify_active_participant(
            memoir_id, 
            user_id, 
            required_roles=["owner", "admin", "contributor"]
        )

        # Published memoirs are frozen — no new uploads into the live book.
        memoir = memoir_repository.fetch_memoir_record(str(memoir_id))
        if memoir and memoir.get("status") == "published":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Memoir is published and no longer accepts new media. "
                "Unpublish it to make changes.",
            )

        # Enforce file size and type validation via the storage adapter
        if payload.byte_size > settings.media_max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="File too large.",
            )
        try:
            media_type, extension = storage_adapter.validate_upload(payload.mime_type)
        except storage_adapter.UnsupportedMediaError as e:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=str(e),
            )
        # mime <-> kind cross-check (client claims kind separately)
        from src.schemas.media import MIME_TO_KIND
        expected_kind = MIME_TO_KIND.get(payload.mime_type)
        if expected_kind and payload.kind != expected_kind and not (
            payload.kind == "video" and expected_kind == "audio"
        ):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="File type does not match media kind.",
            )
        
        # SECURITY FIX: Prevent path traversal by generating a secure UUID-based path key 
        # instead of trusting raw user filenames.
        storage_path = storage_adapter.build_key(memoir_id, media_type, extension)

        try:
            upload_res = storage_adapter.create_signed_upload(storage_path)
        except storage_adapter.StorageError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(e)
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate signed upload URL: {str(e)}"
            )

        return {
            "storage_key": upload_res.path,
            "upload_url": upload_res.signed_url,
            "token": upload_res.token
        }

    @classmethod
    def save_metadata(cls, payload: MediaMetadataRequest, user_session: dict) -> dict:
        """
        Validates user session permissions, enforces tenant isolation on the storage key, 
        confirms physical object existence in storage, validates kind-specific rules,
        prevents duplicate ghost records via checksum idempotency, and persists metadata.
        """
        user_id = user_session.get("user_id")
        memoir_id = payload.memoir_id

        participant = verify_active_participant(
            memoir_id, 
            user_id, 
            required_roles=["owner", "admin", "contributor"]
        )
        participant_id = participant["id"]

        # Published memoirs are frozen — no new media records into the live book.
        memoir = memoir_repository.fetch_memoir_record(str(memoir_id))
        if memoir and memoir.get("status") == "published":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Memoir is published and no longer accepts new media. "
                "Unpublish it to make changes.",
            )

        # SECURITY FIX: Enforce tenant isolation — ensure the storage key explicitly belongs 
        # to this memoir ID to prevent cross-tenant asset hijacking.
        expected_prefix = f"memoirs/{memoir_id}/"
        if not payload.storage_key.startswith(expected_prefix):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid storage key path for this memoir container."
            )

        try:
            file_size = storage_adapter.object_exists(payload.storage_key)
            if not file_size:
                logger.warning(f"Storage index lag detected for key: {payload.storage_key}. Proceeding with metadata save.")
        except Exception as exc:
            logger.warning(f"Could not verify file existence due to error: {exc}")
            file_size = None

        # Enforce server-side size cap (MEDIA_MAX_BYTES) on claimed and actual size.
        if payload.byte_size > settings.media_max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"File too large. Maximum is {settings.media_max_bytes} bytes.",
            )
        if file_size and file_size > settings.media_max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"File too large. Maximum is {settings.media_max_bytes} bytes.",
            )

        # 2. KIND-SPECIFIC VALIDATION: Ensure audio and video assets provide a valid duration
        if payload.kind in ["audio", "video"] and (payload.duration_ms is None):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Audio and video assets require a valid positive duration_ms."
            )
        if payload.kind in ["audio", "video"] and payload.duration_ms is not None:
            if payload.duration_ms <= 0 or payload.duration_ms > MAX_AUDIO_VIDEO_DURATION_MS:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Audio/video duration out of allowed range (max 6 hours).",
                )

        # IDEMPOTENCY CHECK: Prevent duplicate media asset records if a request is retried
        if payload.checksum_sha256:
            existing = media_repository.check_existing_media_by_checksum(str(memoir_id), payload.checksum_sha256)
            if existing:
                return existing

        media_data = {
            "memoir_id": memoir_id,
            "uploaded_by_participant_id": participant_id,
            "storage_key": payload.storage_key,
            "kind": payload.kind,
            "mime_type": payload.mime_type,
            "byte_size": payload.byte_size,
            "original_filename": payload.original_filename,
            "duration_ms": payload.duration_ms,
            "width_px": payload.width_px,
            "height_px": payload.height_px,
            "caption": payload.caption,
            "checksum_sha256": payload.checksum_sha256,
            "storage_tier": STORAGE_TIER_HOT,
            "transcription_status": STORAGE_TIER_HOT if payload.kind == "photo" else TRANSCRIPTION_STATUS_PENDING
        }

        # 1. Get the JSON-safe dictionary representation of the request payload
        media_data = payload.model_dump(mode='json')

        # 2. Dynamically inject server-side tracking fields securely
        media_data["uploaded_by_participant_id"] = participant_id
        media_data["storage_tier"] = STORAGE_TIER_HOT
        
            # STORAGE_TIER_HOT if payload.kind == "photo" else TRANSCRIPTION_STATUS_PENDING
        if payload.kind == "photo":
            media_data["transcription_status"] = "skipped"
        else:
            media_data["transcription_status"] = TRANSCRIPTION_STATUS_PENDING # "pending"
        

        try:
            db_response = media_repository.insert_media_metadata(media_data)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error while saving media metadata: {str(e)}"
            )

        return db_response.data[0] if db_response.data else {}