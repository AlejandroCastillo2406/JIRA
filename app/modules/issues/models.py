from __future__ import annotations
from datetime import date, datetime
from uuid import UUID, uuid4
from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint("project_id", "issue_number", name="uq_project_issue_number"),
        UniqueConstraint("issue_key", name="uq_issue_key"),
        CheckConstraint("story_points IS NULL OR story_points >= 0", name="ck_story_points_nonnegative"),
        CheckConstraint("parent_issue_id IS NULL OR parent_issue_id <> id", name="ck_parent_not_self"),
        CheckConstraint("epic_id IS NULL OR epic_id <> id", name="ck_epic_not_self"),
        Index("ix_issues_project_status", "project_id", "status_id", postgresql_where=text("deleted_at IS NULL")),
        Index("ix_issues_project_assignee", "project_id", "assignee_id", postgresql_where=text("deleted_at IS NULL")),
        Index("ix_issues_project_rank", "project_id", "rank", postgresql_where=text("deleted_at IS NULL")),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    issue_number: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_key: Mapped[str] = mapped_column(String(40), nullable=False)
    type_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("issue_types.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("workflow_statuses.id"), nullable=False)
    priority_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("priorities.id"), nullable=False)
    reporter_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    creator_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    assignee_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    reviewer_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    team_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    epic_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("issues.id"))
    parent_issue_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("issues.id"))
    sprint_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    rank: Mapped[str] = mapped_column(String(12, collation="C"), nullable=False)
    story_points: Mapped[int | None] = mapped_column(SmallInteger)
    due_date: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status = relationship("WorkflowStatus", lazy="joined")
    priority = relationship("Priority", lazy="joined")
    issue_type = relationship("IssueType", lazy="joined")
    assignee = relationship("User", foreign_keys=[assignee_id], lazy="joined")
    reporter = relationship("User", foreign_keys=[reporter_id], lazy="joined")
    reviewer = relationship("User", foreign_keys=[reviewer_id], lazy="joined")


class IssueBlock(Base):
    __tablename__ = "issue_blocks"
    __table_args__ = (Index("uq_issue_open_block", "issue_id", unique=True, postgresql_where=text("unblocked_at IS NULL")),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    issue_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("issues.id", ondelete="CASCADE"), index=True, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    blocked_by_user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    blocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    unblocked_by_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    unblocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IssueImage(Base):
    __tablename__ = "issue_images"
    __table_args__ = (
        Index("ix_issue_images_issue_created", "issue_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    issue_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("issues.id", ondelete="CASCADE"), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(700), unique=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    caption: Mapped[str | None] = mapped_column(String(500))
    uploaded_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
