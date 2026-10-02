from fastapi import APIRouter, BackgroundTasks, Depends, status

from src.core.auth import get_current_user
from src.domain.share_service import ShareService, to_link_response
from src.schemas.share import (
    ShareLinkResponseEnvelope, ShareLinkUpdateRequest, SharedMemoirResponseEnvelope,
    ReaderJoinRequest, ReaderJoinResponseEnvelope, ReaderExportRequest,
    GuestCommentCreate, GuestCommentResponseEnvelope, GuestCommentListEnvelope,
    ReactionToggleRequest, ReactionToggleResponseEnvelope, ReactionSummaryResponseEnvelope,
)

owner_router = APIRouter(prefix="/api/memoirs", tags=["Share Links"])
reader_router = APIRouter(prefix="/api/share", tags=["Shared Memoirs"])

# --- OWNER ROUTES ---
@owner_router.post("/{memoir_id}/share-link", status_code=201, response_model=ShareLinkResponseEnvelope)
async def create_share_link(memoir_id: str, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id") or current_user.get("id") or current_user.get("sub"))
    link = await ShareService.create_or_get_share_link(memoir_id, user_id)
    return {"success": True, "message": "Share link ready.", "data": to_link_response(link)}

@owner_router.patch("/{memoir_id}/share-link", response_model=ShareLinkResponseEnvelope)
async def patch_share_link(memoir_id: str, payload: ShareLinkUpdateRequest, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id") or current_user.get("id") or current_user.get("sub"))
    link = await ShareService.update_share_link(memoir_id, user_id, payload)
    return {"success": True, "message": "Share link updated.", "data": to_link_response(link)}

@owner_router.delete("/{memoir_id}/share-link", status_code=200)
async def delete_share_link(memoir_id: str, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id") or current_user.get("id") or current_user.get("sub"))
    await ShareService.revoke_share_link(memoir_id, user_id)
    return {"success": True, "message": "Share link revoked."}

# --- READER ROUTE (Replaces the need for a separate deps_share.py) ---
@reader_router.get("/{token}", response_model=SharedMemoirResponseEnvelope)
async def read_shared_memoir(token: str):
    data = await ShareService.read_shared_memoir(token)
    return {"success": True, "message": "Operation successful", "data": data}

@reader_router.post("/{token}/join", response_model=ReaderJoinResponseEnvelope)
async def join_shared_memoir(token: str, payload: ReaderJoinRequest):
    data = await ShareService.join_reader(token, payload.display_name)
    return {"success": True, "message": "Welcome.", "data": data}

@reader_router.get("/{token}/comments", response_model=GuestCommentListEnvelope)
async def list_shared_comments(token: str, memory_id: str | None = None):
    data = await ShareService.list_guest_comments(token, memory_id)
    return {"success": True, "message": "Operation successful", "data": data}

@reader_router.post("/{token}/comments", response_model=GuestCommentResponseEnvelope, status_code=status.HTTP_201_CREATED)
async def post_shared_comment(token: str, payload: GuestCommentCreate):
    data = await ShareService.post_guest_comment(token, payload.model_dump())
    return {"success": True, "message": "Comment sent for owner approval.", "data": data}

@reader_router.get("/{token}/reactions", response_model=ReactionSummaryResponseEnvelope)
async def list_shared_reactions(token: str, participant_id: str | None = None):
    data = await ShareService.get_reactions(token, participant_id)
    return {"success": True, "message": "Operation successful", "data": data}

@reader_router.post("/{token}/reactions", response_model=ReactionToggleResponseEnvelope)
async def post_shared_reaction(token: str, payload: ReactionToggleRequest):
    data = await ShareService.post_reaction(token, payload.model_dump())
    return {"success": True, "message": "Operation successful", "data": data}

@reader_router.post("/{token}/export", status_code=status.HTTP_202_ACCEPTED)
async def request_reader_export(token: str, payload: ReaderExportRequest, background_tasks: BackgroundTasks):
    """Reader PDF export for the single live link (images + text only).

    No JWT — the live token plus the joined reader participant_id is the
    credential. Reuses the owner export pipeline, whose payload builder
    strictly excludes comments/reactions.
    """
    job_info = await ShareService.initiate_reader_export(token, payload.participant_id, background_tasks)
    return {"success": True, "data": job_info}

@reader_router.get("/{token}/export/latest")
async def get_reader_export_status(token: str):
    """Latest export status for this live link (poll until ready, then download)."""
    return await ShareService.get_reader_export_status(token)