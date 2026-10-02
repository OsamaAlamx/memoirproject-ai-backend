from datetime import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel, ConfigDict, Field

class ShareLinkUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expires_at: Optional[datetime] = None  # The only thing an owner might realistically update

class ShareLinkResponse(BaseModel):
    id: str
    memoir_id: str
    scope: str
    token: str
    url: str
    created_by_participant_id: Optional[str] = None
    created_at: datetime
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    open_count: int

class ShareLinkResponseEnvelope(BaseModel):
    success: bool = True
    message: str = "Operation successful"
    data: ShareLinkResponse

class SharedMemoirResponseEnvelope(BaseModel):
    success: bool = True
    message: str = "Operation successful"
    data: Dict[str, Any]


class ReaderJoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(..., min_length=1, max_length=100)


class ReaderJoinResponse(BaseModel):
    participant_id: str
    display_name: str
    memoir_id: str


class ReaderJoinResponseEnvelope(BaseModel):
    success: bool = True
    message: str = "Operation successful"
    data: ReaderJoinResponse


class ReaderExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    participant_id: str = Field(..., min_length=1)


class GuestCommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    participant_id: str
    memory_id: Optional[str] = None
    parent_comment_id: Optional[str] = None
    body: str = Field(..., min_length=1, max_length=2000)


class GuestCommentResponse(BaseModel):
    id: str
    memoir_id: str
    memory_id: Optional[str] = None
    parent_comment_id: Optional[str] = None
    body: str
    created_at: datetime
    author_name: str


class GuestCommentResponseEnvelope(BaseModel):
    success: bool = True
    message: str = "Operation successful"
    data: GuestCommentResponse


class GuestCommentListEnvelope(BaseModel):
    success: bool = True
    message: str = "Operation successful"
    data: list[GuestCommentResponse]


class ReactionToggleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    participant_id: str
    memory_id: Optional[str] = None
    media_asset_id: Optional[str] = None
    comment_id: Optional[str] = None
    kind: Optional[str] = "i_remember_this_too"


class ReactionToggleResponse(BaseModel):
    reacted: bool
    count: int


class ReactionToggleResponseEnvelope(BaseModel):
    success: bool = True
    message: str = "Operation successful"
    data: ReactionToggleResponse


class ReactionSummaryResponse(BaseModel):
    counts: Dict[str, int] = {}
    reacted: list[str] = []


class ReactionSummaryResponseEnvelope(BaseModel):
    success: bool = True
    message: str = "Operation successful"
    data: ReactionSummaryResponse