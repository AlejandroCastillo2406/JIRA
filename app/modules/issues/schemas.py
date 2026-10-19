from datetime import date
from pydantic import BaseModel, Field, model_validator
from uuid import UUID


class IssueCreate(BaseModel):
    type_id: UUID
    title: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    priority_id: UUID
    assignee_id: UUID | None = None
    reviewer_id: UUID | None = None
    epic_id: UUID | None = None
    parent_issue_id: UUID | None = None
    story_points: int | None = Field(default=None, ge=0, le=100)
    due_date: date | None = None


class IssueUpdate(BaseModel):
    version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    priority_id: UUID | None = None
    assignee_id: UUID | None = None
    reviewer_id: UUID | None = None
    story_points: int | None = Field(default=None, ge=0, le=100)
    due_date: date | None = None


class TransitionRequest(BaseModel):
    to_status_id: UUID
    version: int = Field(ge=1)
    blocked_reason: str | None = Field(default=None, max_length=3000)


class RankMoveRequest(BaseModel):
    before_issue_id: UUID | None = None
    after_issue_id: UUID | None = None

    @model_validator(mode="after")
    def not_same(self):
        if self.before_issue_id and self.after_issue_id and self.before_issue_id == self.after_issue_id:
            raise ValueError("before_issue_id y after_issue_id no pueden ser iguales")
        return self


class IssueImageUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(gt=0)


class IssueImageConfirm(BaseModel):
    storage_key: str = Field(min_length=1, max_length=700)
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(gt=0)
    caption: str | None = Field(default=None, max_length=500)
