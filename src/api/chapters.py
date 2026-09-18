# src/api/chapters.py
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from typing import List, Dict, Any
from src.domain.chapter_service import ChapterService
from src.core.auth import get_current_user

router = APIRouter(prefix="/api/memoirs", tags=["Chapters"])

class ChapterApplyPayload(BaseModel):
    chapters: List[Dict[str, Any]]

class ChapterRefinePayload(BaseModel):
    current_proposal: Dict[str, Any]
    user_prompt: str

@router.post("/{memoir_id}/chapters/propose", status_code=status.HTTP_200_OK)
def propose_chapters(memoir_id: str, current_user: dict = Depends(get_current_user)):
    """Runs the MCP agent pipeline to generate a self-organized chapter layout."""
    proposal = ChapterService.generate_proposal(memoir_id)
    return {"success": True, "data": proposal}

@router.post("/{memoir_id}/chapters/refine", status_code=status.HTTP_200_OK)
def refine_chapters(memoir_id: str, payload: ChapterRefinePayload, current_user: dict = Depends(get_current_user)):
    """Refines an existing proposal based on a user's chat prompt."""
    refined_proposal = ChapterService.refine_proposal(memoir_id, payload.current_proposal, payload.user_prompt)
    return {"success": True, "data": refined_proposal}

@router.post("/{memoir_id}/chapters/apply", status_code=status.HTTP_200_OK)
def apply_chapters(memoir_id: str, payload: ChapterApplyPayload, current_user: dict = Depends(get_current_user)):
    """Applies the owner-reviewed chapter proposal to the live database."""
    ChapterService.apply_proposal(memoir_id, payload.dict())
    return {"success": True, "message": "Chapters successfully applied."}