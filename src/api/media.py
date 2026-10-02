"""
@file api/media.py
@description FastAPI router for media presigned URLs and metadata.
"""

from fastapi import APIRouter, Depends, status
from src.schemas.media import PresignedUrlRequest, MediaMetadataRequest
from src.domain.media_service import MediaService
from src.core.auth import get_current_user, get_user_id  # Production JWT verification dependency

router = APIRouter(prefix="/api/media", tags=["Media Management"])

@router.post("/presigned-url")
def create_presigned_url(
    payload: PresignedUrlRequest, 
    current_user: dict = Depends(get_current_user)
):
    """
    Generates a presigned storage URL after validating user permissions for the requested memoir.
    """
    user_session = {"user_id": get_user_id(current_user)}
    data = MediaService.generate_presigned_url(payload, user_session)
    return {
        "success": True,
        "data": data
    }

@router.post("/metadata", status_code=status.HTTP_201_CREATED)
def save_metadata(
    payload: MediaMetadataRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Verifies file existence in storage and saves media metadata records.
    """
    user_session = {"user_id": get_user_id(current_user)}
    saved_record = MediaService.save_metadata(payload, user_session)
    return {
        "success": True,
        "message": "Media metadata successfully saved.",
        "data": saved_record
    }