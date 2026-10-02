# src/api/chapters.py
from fastapi import APIRouter, Depends, status
from src.domain.chapter_service import ChapterService
from src.domain.authorization import verify_active_participant
from src.core.auth import get_current_user, get_user_id
from src.schemas.chapters import ChapterApplyPayload, ChapterRefinePayload

router = APIRouter(prefix="/api/memoirs", tags=["Chapters"])


def _require_owner(memoir_id: str, current_user: dict) -> None:
    """Chapter organization reads the whole memoir and spends AI budget,
    so it is owner-only like publication/settings (SEC-B5)."""
    verify_active_participant(str(memoir_id), get_user_id(current_user), required_roles=["owner"])


@router.post("/{memoir_id}/chapters/propose", status_code=status.HTTP_200_OK)
def propose_chapters(memoir_id: str, current_user: dict = Depends(get_current_user)):
    """Runs the MCP agent pipeline to generate a self-organized chapter layout."""
    _require_owner(memoir_id, current_user)
    proposal = ChapterService.generate_proposal(memoir_id)
    return {"success": True, "data": proposal}

@router.post("/{memoir_id}/chapters/refine", status_code=status.HTTP_200_OK)
def refine_chapters(memoir_id: str, payload: ChapterRefinePayload, current_user: dict = Depends(get_current_user)):
    """Refines an existing proposal based on a user's chat prompt."""
    _require_owner(memoir_id, current_user)
    refined_proposal = ChapterService.refine_proposal(memoir_id, payload.current_proposal, payload.user_prompt)
    return {"success": True, "data": refined_proposal}

@router.post("/{memoir_id}/chapters/apply", status_code=status.HTTP_200_OK)
def apply_chapters(memoir_id: str, payload: ChapterApplyPayload, current_user: dict = Depends(get_current_user)):
    """Applies the owner-reviewed chapter proposal to the live database."""
    _require_owner(memoir_id, current_user)
    ChapterService.apply_proposal(memoir_id, payload.model_dump())
    return {"success": True, "message": "Chapters successfully applied."}