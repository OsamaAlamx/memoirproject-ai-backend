"""
@file api/export.py
@description API router for triggering and monitoring memoir PDF exports.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, status
from src.domain.export_service import ExportService
from src.core.auth import get_current_user


router = APIRouter(prefix="/api/memoirs", tags=["Export"])

@router.post("/{memoir_id}/export", status_code=status.HTTP_202_ACCEPTED)
def request_memoir_export(
    memoir_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """
    Initiates an asynchronous PDF export job for the specified memoir.
    Returns 202 Accepted immediately with job status 'queued'.
    """
    from src.core.auth import get_user_id

    job_info = ExportService.initiate_export(
        memoir_id, get_user_id(current_user), background_tasks
    )

    return {
        "success": True,
        "data": job_info
    }
    
@router.get("/{memoir_id}/export/latest")
def get_latest_export_status(
    memoir_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Fetches the latest export job status and signed download URL if ready."""
    return ExportService.get_latest_export_status(memoir_id)