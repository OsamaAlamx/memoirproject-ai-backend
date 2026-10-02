"""
@file transcript.py
@description FastAPI router exposing endpoints to request background transcriptions.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, status
from src.schemas.transcript import TranscriptionRequest
from src.domain.transcription_service import queue_transcription
from src.core.auth import get_current_user

router = APIRouter(prefix="/api/transcript", tags=["Transcript"])

@router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def request_transcription(
    payload: TranscriptionRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """
    Triggers AssemblyAI speech-to-text conversion in the background for a given media asset.
    """
    queue_transcription(
        background_tasks,
        media_asset_id=payload.media_asset_id,
        memoir_id=payload.memoir_id,
        storage_key=payload.storage_key,
    )
    return {"status": "processing", "message": "Transcription task initiated in background."}