"""
@file schemas/media.py
@description Pydantic validation schemas for presigned URL generation and media metadata,
enforcing strict UUID typing, file size limits, media kinds, and path traversal protection on filenames.
"""

import os
import uuid
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class PresignedUrlRequest(BaseModel):
    """
    Validation schema for requesting a direct-to-storage presigned upload URL.
    """
    memoir_id: uuid.UUID = Field(..., description="UUID of the parent memoir")
    filename: str = Field(..., description="Original name of the file being uploaded")
    
    # Aliases 'file_type' from incoming payloads to 'mime_type' for compatibility
    mime_type: str = Field(
        ..., 
        validation_alias="file_type", 
        description="MIME type of the file (e.g., image/jpeg, audio/webm)"
    )
    kind: str = Field(..., description="Media kind: photo, audio, video")
    byte_size: int = Field(..., gt=0, le=52428576, description="Size of the file in bytes")

    @field_validator('filename')
    @classmethod
    def sanitize_filename(cls, v: str) -> str:
        """
        Sanitizes incoming filenames to strip directory traversal characters 
        (e.g., '../', absolute paths) and retain only a safe base filename.

        Args:
            v (str): The raw input filename.

        Returns:
            str: The sanitized base filename.

        Raises:
            ValueError: If the filename contains path traversal attempts or is empty.
        """
        safe_name = os.path.basename(v.strip())
        if not safe_name or ".." in v or "/" in v or "\\" in v:
            raise ValueError("Invalid or unsafe filename provided.")
        return safe_name


MIME_TO_KIND = {
    "image/jpeg": "photo", "image/png": "photo", "image/webp": "photo", "image/heic": "photo",
    "audio/webm": "audio", "audio/ogg": "audio", "audio/mpeg": "audio",
    "audio/mp4": "audio", "audio/wav": "audio",
}

class MediaMetadataRequest(BaseModel):
    """
    Validation schema for persisting media asset metadata after a successful upload.
    """
    memoir_id: uuid.UUID = Field(..., description="UUID of the parent memoir")
    storage_key: str = Field(..., description="Storage path key in Supabase storage")
    kind: str = Field(..., description="Media kind: 'photo', 'audio', or 'video'")
    mime_type: str = Field(..., description="MIME type of the file")
    byte_size: int = Field(..., gt=0, description="Size of the file in bytes")
    original_filename: Optional[str] = Field(None, description="Original filename")
    duration_ms: Optional[int] = Field(None, description="Duration in milliseconds (null for photos)")
    width_px: Optional[int] = Field(None, description="Width in pixels (null for audio)")
    height_px: Optional[int] = Field(None, description="Height in pixels (null for audio)")
    caption: Optional[str] = Field(None, max_length=1000, description="Optional caption for the media")
    checksum_sha256: Optional[str] = Field(None, min_length=64, max_length=64, description="Optional file checksum")
    
    @field_validator('kind')
    @classmethod
    def validate_media_kind(cls, v: str) -> str:
        """
        Ensures media kind is within the permitted classification set.
        """
        allowed_kinds = {'photo', 'audio', 'video'}
        if v not in allowed_kinds:
            raise ValueError(f"Invalid media kind '{v}'. Must be one of {allowed_kinds}.")
        return v

    @field_validator('mime_type')
    @classmethod
    def validate_mime_matches_kind(cls, v: str, info) -> str:
        kind = (info.data or {}).get("kind")
        expected = MIME_TO_KIND.get(v)
        if expected is None:
            raise ValueError("Unsupported file type.")
        # video kind currently shares audio mime set client-side; allow audio mimes for video
        if kind and kind != expected and not (kind == "video" and expected == "audio"):
            raise ValueError(f"MIME {v} does not match kind {kind}.")
        return v