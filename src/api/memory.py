"""
@file api/memory.py
@description FastAPI router for owner memory capture, feed retrieval, edit, and pre-publication management.
"""

from fastapi import APIRouter, Depends, status, Body
from src.schemas.memory import MemoryCreateRequest
from src.domain.memory_service import MemoryService
from src.core.auth import get_current_user

router = APIRouter(prefix="/api/memories", tags=["Memories"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_memory(
    payload: MemoryCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user.get("user_id") or current_user.get("id") or current_user.get("sub")
    user_session = {"user_id": user_id}

    result = MemoryService.create_memory(payload, user_session)
    return {
        "success": True,
        "message": "Memory successfully created.",
        "data": result
    }


@router.get("/feed/{memoir_id}", status_code=status.HTTP_200_OK)
def get_memoir_feed_route(
    memoir_id: str,
    limit: int = 20,
    offset: int = 0,
    user_session: dict = Depends(get_current_user)
):
    user_id = user_session.get("user_id")
    feed_data = MemoryService.get_memoir_feed(memoir_id, user_id, limit=limit, offset=offset)
    return {"success": True, "data": feed_data}


@router.patch("/{memory_id}", status_code=status.HTTP_200_OK)
def update_memory_route(
    memory_id: str,
    payload: dict = Body(...),
    user_session: dict = Depends(get_current_user)
):
    """
    Updates a memory's title, body_text, or occurred_start date.
    """
    user_id = user_session.get("user_id")
    result = MemoryService.update_memory(memory_id, user_id, payload)
    return result


@router.delete("/{memory_id}", status_code=status.HTTP_200_OK)
def delete_memory_by_id_route(
    memory_id: str,
    user_session: dict = Depends(get_current_user)
):
    user_id = user_session.get("user_id")
    result = MemoryService.delete_memory_by_id(memory_id, user_id)
    return {"success": True, "data": result}


@router.delete("/memoirs/{memoir_id}/memories/{memory_id}", status_code=status.HTTP_200_OK)
def delete_memory_route(memoir_id: str, memory_id: str, user_session: dict = Depends(get_current_user)):
    user_id = user_session.get("user_id")
    result = MemoryService.delete_memory(memoir_id, memory_id, user_id)
    return {"success": True, "data": result}