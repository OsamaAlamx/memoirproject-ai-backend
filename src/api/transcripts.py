"""
@file transcript.py
@description FastAPI router exposing endpoints to request background transcriptions.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, status
from src.schemas.transcript import TranscriptionRequest
from src.domain.transcription_service import queue_transcription
from src.core.auth import get_current_user
from src.core.rate_limit import transcript_limit

router = APIRouter(prefix="/api/transcript", tags=["Transcript"])

@router.post("/", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(transcript_limit)])
async def request_transcription(
    payload: TranscriptionRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """
    Triggers AssemblyAI speech-to-text conversion in the background for a given media asset.
    Caller must be an active participant of the memoir; storage_key is confined
    to that memoir's prefix to prevent cross-tenant fetch / budget burn.
    """
    from src.core.auth import get_user_id
    from src.domain.authorization import verify_active_participant
    from fastapi import HTTPException, status
    user_id = get_user_id(current_user)
    memoir_id = str(payload.memoir_id)
    verify_active_participant(memoir_id, user_id)
    expected_prefix = f"memoirs/{memoir_id}/"
    if not str(payload.storage_key).startswith(expected_prefix):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Storage key does not belong to this memoir.",
        )
    queue_transcription(
        background_tasks,
        media_asset_id=payload.media_asset_id,
        memoir_id=payload.memoir_id,
        storage_key=payload.storage_key,
    )
    return {"status": "processing", "message": "Transcription task initiated in background."}