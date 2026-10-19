from __future__ import annotations
from uuid import UUID, uuid4
from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class IssueType(Base):
    __tablename__ = "issue_types"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_issue_type_scope_code"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(40))
    is_epic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_subtask: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Priority(Base):
    __tablename__ = "priorities"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_priority_scope_code"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False)


class Workflow(Base):
    __tablename__ = "workflows"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    statuses: Mapped[list[WorkflowStatus]] = relationship(back_populates="workflow", lazy="selectin")


class WorkflowStatus(Base):
    __tablename__ = "workflow_statuses"
    __table_args__ = (UniqueConstraint("workflow_id", "code", name="uq_workflow_status_code"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False)
    is_initial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    workflow: Mapped[Workflow] = relationship(back_populates="statuses")


class WorkflowTransition(Base):
    __tablename__ = "workflow_transitions"
    __table_args__ = (UniqueConstraint("workflow_id", "from_status_id", "to_status_id", name="uq_workflow_transition"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    from_status_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("workflow_statuses.id", ondelete="CASCADE"), nullable=False)
    to_status_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("workflow_statuses.id", ondelete="CASCADE"), nullable=False)
    required_permission: Mapped[str | None] = mapped_column(String(100))
    required_fields: Mapped[list[str] | None] = mapped_column(ARRAY(String()))
