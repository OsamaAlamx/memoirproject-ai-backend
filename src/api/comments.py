"""
@file routers/comments_router.py
@description FastAPI router endpoints for comment operations.
"""

from fastapi import APIRouter, Depends, Query, status
from typing import List
from src.schemas.comments import CommentCreate, CommentResponse
from src.domain.comments_service import CommentsService
from src.core.auth import get_current_user
router = APIRouter(prefix="/api/comments", tags=["Comments"])

@router.get("/", response_model=List[CommentResponse])
async def list_comments(
    memory_id: str = Query(..., description="The UUID of the memory item"),
    current_user: dict = Depends(get_current_user),
):
    """Fetch all comments linked to a specific memory asset."""
    return await CommentsService.get_memory_comments(memory_id)

@router.post("/", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
async def post_comment(
    payload: CommentCreate,
    current_user: dict = Depends(get_current_user)
):
    """Post a new comment to a memory item with automatic participant resolution."""
    user_id = str(current_user.get("user_id") or current_user.get("id") or current_user.get("sub"))
    return await CommentsService.create_new_comment(payload.model_dump(), user_id)

@router.get("/pending", response_model=List[CommentResponse])
async def list_pending_comments(
    memoir_id: str = Query(..., description="The UUID of the memoir"),
    current_user: dict = Depends(get_current_user),
):
    """Owner-only: guest comments awaiting approval."""
    user_id = str(current_user.get("user_id") or current_user.get("id") or current_user.get("sub"))
    return await CommentsService.get_pending_for_owner(memoir_id, user_id)

@router.patch("/{comment_id}/approve", response_model=CommentResponse)
async def approve_comment(
    comment_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Owner-only: approve a pending comment so readers can see it."""
    user_id = str(current_user.get("user_id") or current_user.get("id") or current_user.get("sub"))
    return await CommentsService.approve_for_owner(comment_id, user_id)

@router.delete("/{comment_id}")
async def reject_comment(
    comment_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Owner-only reject: permanently deletes the comment."""
    user_id = str(current_user.get("user_id") or current_user.get("id") or current_user.get("sub"))
    return {"success": True, "data": await CommentsService.reject_for_owner(comment_id, user_id)}