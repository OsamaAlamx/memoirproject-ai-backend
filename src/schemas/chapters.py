from typing import List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


class ChapterApplyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapters: List[Dict[str, Any]]


class ChapterRefinePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_proposal: Dict[str, Any]
    # Empty prompts previously slipped through to a full-price LLM call.
    user_prompt: str = Field(min_length=1)
