"""
@file services/comments_service.py
@description Business logic layer for comment processing.
"""

from typing import List, Dict, Any
from src.integrations.comments_repository import (
    CommentsRepository, RepositoryError, NotParticipantError,
)
from src.domain.authorization import verify_active_participant
from fastapi import HTTPException, status

class CommentsService:

    @staticmethod
    async def get_memory_comments(memory_id: str, user_id: str) -> List[Dict[str, Any]]:
        if not memory_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Memory ID is required."
            )
        try:
            # Resolve memoir for authz before returning any rows (no existence oracle).
            memoir_id = await CommentsRepository.get_memory_memoir_id(memory_id)
            if not memoir_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Comments not found."
                )
            verify_active_participant(str(memoir_id), str(user_id))
            return await CommentsRepository.get_comments_by_memory_id(memory_id)
        except HTTPException:
            raise
        except RepositoryError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not load comments.",
            )

    @staticmethod
    async def create_new_comment(payload: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        if not payload.get("body") or not payload["body"].strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Comment text cannot be empty."
            )
        try:
            return await CommentsRepository.insert_comment(payload, user_id)
        except NotParticipantError as e:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(e),
            )
        except RepositoryError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    @staticmethod
    async def _owner_memoir_of_comment(comment_id: str, user_id: str) -> str:
        memoir_id = await CommentsRepository.get_comment_memoir_id(comment_id)
        if not memoir_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found.")
        verify_active_participant(str(memoir_id), str(user_id), required_roles=["owner"])
        return str(memoir_id)

    @staticmethod
    async def get_pending_for_owner(memoir_id: str, user_id: str) -> List[Dict[str, Any]]:
        verify_active_participant(str(memoir_id), str(user_id), required_roles=["owner"])
        try:
            return await CommentsRepository.get_pending_comments(str(memoir_id))
        except RepositoryError:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not load comments.")

    @staticmethod
    async def approve_for_owner(comment_id: str, user_id: str) -> Dict[str, Any]:
        await CommentsService._owner_memoir_of_comment(comment_id, user_id)
        try:
            return await CommentsRepository.approve_comment(comment_id)
        except RepositoryError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @staticmethod
    async def reject_for_owner(comment_id: str, user_id: str) -> Dict[str, Any]:
        """Reject = permanent delete (replies cascade per schema)."""
        await CommentsService._owner_memoir_of_comment(comment_id, user_id)
        try:
            return await CommentsRepository.delete_comment_hard(comment_id)
        except RepositoryError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))