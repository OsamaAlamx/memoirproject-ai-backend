from pydantic import BaseModel, Field, model_validator
from typing import Optional, Literal
from datetime import date
import uuid

class MemoirCreateRequest(BaseModel):
    subject_name: str = Field(..., description="Name of the subject of the memoir")
    subject_born_on: Optional[date] = Field(None, description="Birth date of the subject (YYYY-MM-DD)")
    subject_died_on: Optional[date] = Field(None, description="Death date of the subject (YYYY-MM-DD)")
    subject_is_living: bool = Field(False, description="Whether the subject is currently alive")
    description: Optional[str] = Field(None, description="Optional description or blurb for the memoir")
    visibility: Optional[str] = Field("invited_only", description="Visibility setting: 'invited_only', 'public', or 'link_with_password'")
    comment_policy: Optional[str] = Field("invited_only", description="Comment policy setting")
    relationship: Optional[Literal[
    "self", "spouse_partner", "parent", "child", 
    "sibling", "grandchild", "extended_family", 
    "friend", "colleague", "neighbour", "other"
    ]] = Field("other", description="Relationship of the creator to the memoir subject")

    @model_validator(mode='after')
    def validate_memoir_constraints(self) -> 'MemoirCreateRequest':
        if self.subject_born_on and self.subject_died_on:
            if self.subject_born_on > self.subject_died_on:
                raise ValueError("Subject birth date cannot be after their death date.")
        if self.subject_is_living and self.subject_died_on is not None:
            raise ValueError("A living subject cannot have a death date.")
        return self


class MemoirResponseData(BaseModel):
    """The raw memoir record returned inside the data envelope."""
    id: uuid.UUID
    subject_name: str
    subject_born_on: Optional[date] = None
    subject_died_on: Optional[date] = None
    subject_is_living: bool
    description: Optional[str] = None
    visibility: str
    comment_policy: str
    created_by_user_id: uuid.UUID
    status: str


class MemoirResponseEnvelope(BaseModel):
    """Consistent API response envelope for frontend consumption and OpenAPI documentation."""
    success: bool = True
    message: str = "Operation successful"
    data: MemoirResponseData


class MemoirPublicationRequest(BaseModel):
    publish: bool = Field(..., description="True to go live, False to take down.")


class MemoirSettingsRequest(BaseModel):
    comment_policy: Optional[Literal["nobody", "invited_only", "anyone_who_can_view"]] = Field(
        None, description="Who may comment on the shared memoir.")
    visibility: Optional[Literal["invited_only", "link_with_password", "link_public"]] = Field(
        None, description="Who may open the shared memoir.")