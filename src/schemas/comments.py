"""
@file schemas/comment_schemas.py
@description Pydantic validation schemas for comment requests and responses.
"""

from pydantic import BaseModel, ConfigDict
from typing import Optional

class CommentCreate(BaseModel):
    memoir_id: str
    memory_id: Optional[str] = None   # was: str (required)
    media_asset_id: Optional[str] = None
    parent_comment_id: Optional[str] = None
    body: str

class CommentResponse(BaseModel):
    id: str
    memoir_id: str
    memory_id: Optional[str] = None
    media_asset_id: Optional[str] = None
    author_participant_id: str
    parent_comment_id: Optional[str] = None
    body: str
    created_at: str
    updated_at: Optional[str] = None
    author_name: str

    model_config = ConfigDict(from_attributes=True)