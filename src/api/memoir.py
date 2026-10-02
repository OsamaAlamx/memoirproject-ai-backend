"""
@file api/memoir.py
@description FastAPI router handling HTTP endpoints for memoir creation, 
management, and live memoir retrieval.
"""

from fastapi import APIRouter, Depends, status
from src.schemas.memoir import MemoirCreateRequest, MemoirResponseEnvelope, MemoirPublicationRequest, MemoirSettingsRequest
from src.domain.memoir_service import MemoirService
from src.core.auth import get_current_user

router = APIRouter(prefix="/api/memoirs", tags=["Memoirs"])


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=MemoirResponseEnvelope)
def create_memoir(
    payload: MemoirCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Creates a new root memoir container for a subject. 
    This must be executed first to obtain a memoir_id before adding media or memories.
    """
    user_id = current_user.get("user_id") or current_user.get("id") or current_user.get("sub")
    
    user_session = {"user_id": user_id}
    new_memoir = MemoirService.create_memoir(payload, user_session)
    return {
        "success": True,
        "message": "Memoir successfully created.",
        "data": new_memoir
    }


@router.get("/user/active", status_code=status.HTTP_200_OK)
def get_user_active_memoir(
    current_user: dict = Depends(get_current_user)
):
    """
    Fetches the active memoir belonging to the authenticated user.
    """
    user_id = current_user.get("user_id") or current_user.get("id") or current_user.get("sub")
    memoir = MemoirService.get_user_active_memoir(str(user_id))
    return {
        "success": True,
        "data": memoir
    }


@router.get("/", status_code=status.HTTP_200_OK)
def list_user_memoirs(
    current_user: dict = Depends(get_current_user)
):
    """
    Lists every memoir owned by the authenticated user, newest first.
    """
    user_id = current_user.get("user_id") or current_user.get("id") or current_user.get("sub")
    memoirs = MemoirService.list_user_memoirs(str(user_id))
    return {
        "success": True,
        "data": memoirs
    }


@router.delete("/{memoir_id}", status_code=status.HTTP_200_OK)
def delete_memoir(
    memoir_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Deletes a memoir owned by the authenticated user. Child rows
    (participants, chapters, memories, media, comments, exports)
    cascade off the memoir row per the database schema.
    """
    user_id = current_user.get("user_id") or current_user.get("id") or current_user.get("sub")
    deleted = MemoirService.delete_memoir(memoir_id, str(user_id))
    return {
        "success": True,
        "message": "Memoir deleted.",
        "data": deleted
    }


@router.get("/{memoir_id}/live", status_code=status.HTTP_200_OK)
def get_live_memoir(
    memoir_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Retrieves live memoir metadata, chapters, and memory entries for active participants.
    """
    user_id = current_user.get("user_id") or current_user.get("id") or current_user.get("sub")
    data = MemoirService.get_live_memoir(memoir_id, user_id)
    return {
        "success": True,
        "data": data
    }


@router.patch("/{memoir_id}/publication", status_code=status.HTTP_200_OK)
def set_memoir_publication(
    memoir_id: str,
    payload: MemoirPublicationRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Go-live switch, owner-only. Publish serves the memoir on its share link;
    unpublish returns it to draft. Drafts never serve, even with a live link.
    """
    user_id = current_user.get("user_id") or current_user.get("id") or current_user.get("sub")
    updated = MemoirService.set_memoir_publication(memoir_id, str(user_id), payload.publish)
    return {
        "success": True,
        "message": "Memoir published." if payload.publish else "Memoir unpublished.",
        "data": updated
    }


@router.patch("/{memoir_id}/settings", status_code=status.HTTP_200_OK)
def set_memoir_settings(
    memoir_id: str,
    payload: MemoirSettingsRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Owner-only publication settings: who may comment and who may open the
    shared memoir. Readers commenting requires comment_policy anyone_who_can_view.
    """
    user_id = current_user.get("user_id") or current_user.get("id") or current_user.get("sub")
    updated = MemoirService.set_memoir_settings(memoir_id, str(user_id), payload.model_dump())
    return {
        "success": True,
        "message": "Memoir settings updated.",
        "data": updated
    }