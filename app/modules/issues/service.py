from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AppError
from app.core.outbox import enqueue_event
from app.core.permissions import (
    Permission,
    can_manage_project,
    ensure_issue_update,
    ensure_issue_visible,
    ensure_project_manager,
    ensure_project_permission,
)
from app.core.rank import next_rank, rank_between
from app.integrations.email.ses import send_issue_assignment_email
from app.modules.issues.image_service import image_view
from app.modules.issues.models import Issue, IssueBlock
from app.modules.issues.repository import get_issue
from app.modules.projects.models import Project, ProjectMember
from app.modules.users.models import User
from app.modules.workflows.models import IssueType, Priority, WorkflowStatus, WorkflowTransition


def issue_view(issue: Issue, images=None, active_block=None) -> dict:
    image_rows = list(images or [])
    image_payload = [image_view(row) for row in image_rows]
    return {
        "id": str(issue.id), "project_id": str(issue.project_id), "issue_number": issue.issue_number,
        "issue_key": issue.issue_key, "title": issue.title, "description": issue.description,
        "version": issue.version, "rank": issue.rank, "story_points": issue.story_points,
        "due_date": issue.due_date.isoformat() if issue.due_date else None,
        "created_at": issue.created_at.isoformat(), "updated_at": issue.updated_at.isoformat(),
        "started_at": issue.started_at.isoformat() if issue.started_at else None,
        "completed_at": issue.completed_at.isoformat() if issue.completed_at else None,
        "type": {"id": str(issue.issue_type.id), "code": issue.issue_type.code, "name": issue.issue_type.name},
        "status": {"id": str(issue.status.id), "code": issue.status.code, "name": issue.status.name,
                   "category": issue.status.category, "color": issue.status.color},
        "priority": {"id": str(issue.priority.id), "code": issue.priority.code, "name": issue.priority.name,
                     "rank": issue.priority.rank, "color": issue.priority.color},
        "assignee": ({"id": str(issue.assignee.id), "display_name": issue.assignee.display_name,
                      "email": issue.assignee.email} if issue.assignee else None),
        "reporter": {"id": str(issue.reporter.id), "display_name": issue.reporter.display_name,
                     "email": issue.reporter.email},
        "reviewer": ({"id": str(issue.reviewer.id), "display_name": issue.reviewer.display_name,
                      "email": issue.reviewer.email} if issue.reviewer else None),
        "epic_id": str(issue.epic_id) if issue.epic_id else None,
        "parent_issue_id": str(issue.parent_issue_id) if issue.parent_issue_id else None,
        # El archivo nunca se guarda en PostgreSQL: estas son URLs prefirmadas temporales de S3.
        "images": image_payload,
        "image_count": len(image_payload),
        "cover_image": image_payload[0] if image_payload else None,
        "active_block": active_block,
    }


async def _validate_user_membership(session: AsyncSession, project_id: UUID, user_id: UUID | None, field: str) -> None:
    if not user_id:
        return
    exists = await session.scalar(select(ProjectMember.user_id).where(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == user_id,
    ))
    if not exists:
        raise AppError("INVALID_PROJECT_MEMBER", f"{field} debe pertenecer al proyecto", 422)


async def _send_assignment_emails(session: AsyncSession, *, issue_key: str, title: str,
                                  assignments: dict[UUID, list[str]]) -> None:
    if not assignments:
        return
    users = list((await session.scalars(select(User).where(User.id.in_(list(assignments))))).all())
    by_id = {u.id: u for u in users}
    for user_id, roles in assignments.items():
        target = by_id.get(user_id)
        if not target:
            continue
        await send_issue_assignment_email(
            to_email=target.email,
            display_name=target.display_name,
            issue_key=issue_key,
            issue_title=title,
            roles=roles,
        )


def _assignment_map(assignee_id: UUID | None, reviewer_id: UUID | None) -> dict[UUID, list[str]]:
    assignments: dict[UUID, list[str]] = {}
    if assignee_id:
        assignments.setdefault(assignee_id, []).append("responsable")
    if reviewer_id:
        assignments.setdefault(reviewer_id, []).append("revisor")
    return assignments


async def create_issue(session: AsyncSession, user, project_id: UUID, data, request_id: str | None) -> Issue:
    await ensure_project_permission(session, user, project_id, Permission.ISSUE_CREATE)
    # La creación/asignación de trabajo queda reservada a administración o al PROJECT_MANAGER.
    await ensure_project_manager(session, user, project_id)
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.status == "ACTIVE"))
    if not project:
        raise AppError("NOT_FOUND", "Proyecto no encontrado", 404)

    issue_type = await session.scalar(select(IssueType).where(
        IssueType.id == data.type_id,
        or_(IssueType.project_id.is_(None), IssueType.project_id == project_id),
        IssueType.is_active.is_(True),
    ))
    priority = await session.scalar(select(Priority).where(
        Priority.id == data.priority_id,
        or_(Priority.project_id.is_(None), Priority.project_id == project_id),
    ))
    initial = await session.scalar(select(WorkflowStatus).where(
        WorkflowStatus.workflow_id == project.default_workflow_id,
        WorkflowStatus.is_initial.is_(True),
    ))
    if not issue_type or not priority or not initial:
        raise AppError("INVALID_CATALOG", "Tipo, prioridad o workflow inválido", 422)

    await _validate_user_membership(session, project_id, data.assignee_id, "assignee_id")
    await _validate_user_membership(session, project_id, data.reviewer_id, "reviewer_id")

    if data.epic_id:
        epic = await session.scalar(select(Issue).where(
            Issue.id == data.epic_id, Issue.project_id == project_id, Issue.deleted_at.is_(None)
        ))
        if not epic or not epic.issue_type.is_epic:
            raise AppError("INVALID_EPIC", "La épica debe existir en el mismo proyecto", 422)
    if data.parent_issue_id:
        parent = await session.scalar(select(Issue).where(
            Issue.id == data.parent_issue_id, Issue.project_id == project_id, Issue.deleted_at.is_(None)
        ))
        if not parent or parent.parent_issue_id is not None:
            raise AppError("INVALID_PARENT", "Solo se permite un nivel de subtarea", 422)

    number = await session.scalar(
        update(Project).where(Project.id == project_id)
        .values(issue_counter=Project.issue_counter + 1)
        .returning(Project.issue_counter)
    )
    last_rank = await session.scalar(
        select(Issue.rank)
        .where(Issue.project_id == project_id, Issue.deleted_at.is_(None))
        .order_by(Issue.rank.desc()).limit(1)
    )
    issue = Issue(
        project_id=project_id,
        issue_number=number,
        issue_key=f"{project.key}-{number}",
        type_id=data.type_id,
        title=data.title,
        description=data.description,
        status_id=initial.id,
        priority_id=data.priority_id,
        reporter_id=user.id,
        creator_id=user.id,
        assignee_id=data.assignee_id,
        reviewer_id=data.reviewer_id,
        epic_id=data.epic_id,
        parent_issue_id=data.parent_issue_id,
        story_points=data.story_points,
        due_date=data.due_date,
        rank=next_rank(last_rank),
    )
    session.add(issue)
    await session.flush()

    await record_audit(
        session, entity_type="issue", entity_id=issue.id, project_id=project_id,
        action="ISSUE_CREATED", actor_user_id=user.id, new_value=issue.title, request_id=request_id,
    )
    await enqueue_event(
        session, event_type="IssueCreated", aggregate_type="issue", aggregate_id=issue.id,
        payload={
            "project_id": str(project_id), "actor_user_id": str(user.id),
            "assignee_id": str(issue.assignee_id) if issue.assignee_id else None,
            "reviewer_id": str(issue.reviewer_id) if issue.reviewer_id else None,
            "issue_key": issue.issue_key, "title": issue.title,
        },
    )

    # SES directo: si SES_FROM_EMAIL está configurado, el endpoint espera a que SES acepte el correo.
    await _send_assignment_emails(
        session,
        issue_key=issue.issue_key,
        title=issue.title,
        assignments=_assignment_map(issue.assignee_id, issue.reviewer_id),
    )
    await session.commit()
    return await get_issue(session, str(issue.id))


async def update_issue(session: AsyncSession, user, identifier: str, data, request_id: str | None) -> Issue:
    issue = await get_issue(session, identifier)
    if not issue:
        raise AppError("NOT_FOUND", "Ticket no encontrado", 404)
    await ensure_issue_update(session, user, issue)
    if issue.version != data.version:
        raise AppError("ISSUE_VERSION_CONFLICT", "El ticket cambió. Recarga antes de guardar.", 409,
                       {"current_version": issue.version})

    requested_changes = data.model_dump(exclude_unset=True, exclude={"version"})
    # Evita incrementar version, auditar o disparar validaciones por campos que el
    # frontend envió con el mismo valor actual.
    changes = {
        field: value
        for field, value in requested_changes.items()
        if getattr(issue, field) != value
    }
    if not changes:
        return issue

    if "assignee_id" in changes or "reviewer_id" in changes:
        # Un miembro puede actualizar su propio ticket, pero no reasignarlo a otra persona.
        await ensure_project_manager(session, user, issue.project_id)
    if "assignee_id" in changes:
        await _validate_user_membership(session, issue.project_id, changes["assignee_id"], "assignee_id")
    if "reviewer_id" in changes:
        await _validate_user_membership(session, issue.project_id, changes["reviewer_id"], "reviewer_id")
    if "priority_id" in changes and changes["priority_id"] is not None:
        valid_priority = await session.scalar(select(Priority.id).where(
            Priority.id == changes["priority_id"],
            or_(Priority.project_id.is_(None), Priority.project_id == issue.project_id),
        ))
        if not valid_priority:
            raise AppError("INVALID_PRIORITY", "Prioridad inválida", 422)

    old = {field: getattr(issue, field) for field in changes}
    result = await session.execute(
        update(Issue)
        .where(Issue.id == issue.id, Issue.version == data.version)
        .values(**changes, version=Issue.version + 1, updated_at=func.now())
    )
    if result.rowcount != 1:
        await session.rollback()
        raise AppError("ISSUE_VERSION_CONFLICT", "El ticket cambió. Recarga antes de guardar.", 409)

    for field, value in changes.items():
        if old[field] != value:
            await record_audit(
                session, entity_type="issue", entity_id=issue.id, project_id=issue.project_id,
                action="ISSUE_UPDATED", actor_user_id=user.id, field_name=field,
                old_value=str(old[field]) if old[field] is not None else None,
                new_value=str(value) if value is not None else None,
                request_id=request_id,
            )

    new_assignee = changes.get("assignee_id", issue.assignee_id)
    new_reviewer = changes.get("reviewer_id", issue.reviewer_id)
    await enqueue_event(
        session, event_type="IssueUpdated", aggregate_type="issue", aggregate_id=issue.id,
        payload={
            "project_id": str(issue.project_id), "actor_user_id": str(user.id),
            "assignee_id": str(new_assignee) if new_assignee else None,
            "reviewer_id": str(new_reviewer) if new_reviewer else None,
            "issue_key": issue.issue_key,
        },
    )

    assignments: dict[UUID, list[str]] = {}
    if "assignee_id" in changes and changes["assignee_id"] and changes["assignee_id"] != old["assignee_id"]:
        assignments.setdefault(changes["assignee_id"], []).append("responsable")
    if "reviewer_id" in changes and changes["reviewer_id"] and changes["reviewer_id"] != old["reviewer_id"]:
        assignments.setdefault(changes["reviewer_id"], []).append("revisor")
    await _send_assignment_emails(
        session,
        issue_key=issue.issue_key,
        title=changes.get("title", issue.title),
        assignments=assignments,
    )

    await session.commit()
    return await get_issue(session, str(issue.id))


async def transition_issue(session: AsyncSession, user, identifier: str, data, request_id: str | None) -> Issue:
    issue = await get_issue(session, identifier)
    if not issue:
        raise AppError("NOT_FOUND", "Ticket no encontrado", 404)
    # Cambiar estado no equivale a editar el ticket. Developer/Reviewer pueden
    # ejecutar únicamente las transiciones autorizadas por el workflow y sus permisos.
    await ensure_issue_visible(session, user, issue)
    if issue.version != data.version:
        raise AppError("ISSUE_VERSION_CONFLICT", "El ticket cambió. Recarga antes de moverlo.", 409,
                       {"current_version": issue.version})

    target = await session.scalar(select(WorkflowStatus).where(
        WorkflowStatus.id == data.to_status_id,
        WorkflowStatus.workflow_id == issue.status.workflow_id,
    ))
    transition = await session.scalar(select(WorkflowTransition).where(
        WorkflowTransition.workflow_id == issue.status.workflow_id,
        WorkflowTransition.from_status_id == issue.status_id,
        WorkflowTransition.to_status_id == data.to_status_id,
    ))
    if not target or not transition:
        raise AppError("INVALID_TRANSITION", "La transición solicitada no está permitida", 422)

    if transition.required_permission:
        try:
            required_permission = Permission(transition.required_permission)
        except ValueError as exc:
            raise AppError("WORKFLOW_CONFIG_ERROR", "El workflow tiene un permiso no reconocido", 500) from exc
        await ensure_project_permission(session, user, issue.project_id, required_permission)

        # La lectura del detalle es abierta a miembros del proyecto, pero mover
        # trabajo sigue ligado a la asignación concreta del ticket.
        if not await can_manage_project(session, user, issue.project_id):
            if required_permission == Permission.ISSUE_PROGRESS and issue.assignee_id != user.id:
                raise AppError("FORBIDDEN", "Solo el responsable puede mover el trabajo del Developer", 403)
            if required_permission == Permission.VALIDATION_DECIDE and issue.reviewer_id != user.id:
                raise AppError("FORBIDDEN", "Solo el revisor asignado puede validar este ticket", 403)
    for field in transition.required_fields or []:
        if not getattr(issue, field, None):
            raise AppError("REQUIRED_FIELD_MISSING", f"El campo {field} es obligatorio para esta transición", 422,
                           {"field": field})

    if target.code == "BLOCKED" and not data.blocked_reason:
        raise AppError("BLOCK_REASON_REQUIRED", "Indica el motivo del bloqueo", 422)
    if target.category == "IN_PROGRESS" and not issue.assignee_id:
        raise AppError("ASSIGNEE_REQUIRED", "Asigna un responsable antes de iniciar el trabajo", 422)

    now = datetime.now(timezone.utc)
    values = {"status_id": target.id, "version": Issue.version + 1, "updated_at": func.now()}
    if target.category == "IN_PROGRESS" and issue.started_at is None:
        values["started_at"] = now
    if target.category == "DONE":
        values["completed_at"] = now
    elif issue.status.category == "DONE":
        values["completed_at"] = None

    result = await session.execute(
        update(Issue).where(Issue.id == issue.id, Issue.version == data.version).values(**values)
    )
    if result.rowcount != 1:
        await session.rollback()
        raise AppError("ISSUE_VERSION_CONFLICT", "El ticket cambió. Recarga antes de moverlo.", 409)

    open_block = await session.scalar(select(IssueBlock).where(
        IssueBlock.issue_id == issue.id, IssueBlock.unblocked_at.is_(None)
    ))
    if target.code == "BLOCKED" and not open_block:
        session.add(IssueBlock(issue_id=issue.id, reason=data.blocked_reason, blocked_by_user_id=user.id))
        await record_audit(
            session, entity_type="issue", entity_id=issue.id, project_id=issue.project_id,
            action="ISSUE_BLOCKED", actor_user_id=user.id, new_value=data.blocked_reason, request_id=request_id,
        )
    elif target.code != "BLOCKED" and open_block:
        open_block.unblocked_at = now
        open_block.unblocked_by_user_id = user.id
        await record_audit(
            session, entity_type="issue", entity_id=issue.id, project_id=issue.project_id,
            action="ISSUE_UNBLOCKED", actor_user_id=user.id, request_id=request_id,
        )

    await record_audit(
        session, entity_type="issue", entity_id=issue.id, project_id=issue.project_id,
        action="STATUS_CHANGED", actor_user_id=user.id, field_name="status_id",
        old_value=str(issue.status_id), new_value=str(target.id),
        metadata={"old": issue.status.name, "new": target.name}, request_id=request_id,
    )
    await enqueue_event(
        session, event_type="IssueStatusChanged", aggregate_type="issue", aggregate_id=issue.id,
        payload={
            "project_id": str(issue.project_id), "actor_user_id": str(user.id),
            "assignee_id": str(issue.assignee_id) if issue.assignee_id else None,
            "reviewer_id": str(issue.reviewer_id) if issue.reviewer_id else None,
            "issue_key": issue.issue_key, "status": target.name,
        },
    )
    await session.commit()
    return await get_issue(session, str(issue.id))


async def move_rank(session: AsyncSession, user, identifier: str, before_id: UUID | None, after_id: UUID | None,
                    request_id: str | None) -> Issue:
    issue = await get_issue(session, identifier)
    if not issue:
        raise AppError("NOT_FOUND", "Ticket no encontrado", 404)
    await ensure_issue_update(session, user, issue)
    before = await session.scalar(select(Issue).where(
        Issue.id == before_id, Issue.project_id == issue.project_id
    )) if before_id else None
    after = await session.scalar(select(Issue).where(
        Issue.id == after_id, Issue.project_id == issue.project_id
    )) if after_id else None
    new_rank = rank_between(before.rank if before else None, after.rank if after else None)
    if new_rank is None:
        raise AppError("RANK_REBALANCE_REQUIRED", "No hay espacio de orden entre tickets; ejecuta rebalanceo", 409)
    old = issue.rank
    issue.rank = new_rank
    issue.version += 1
    await record_audit(
        session, entity_type="issue", entity_id=issue.id, project_id=issue.project_id,
        action="RANK_CHANGED", actor_user_id=user.id, field_name="rank", old_value=old,
        new_value=new_rank, request_id=request_id,
    )
    await session.commit()
    return await get_issue(session, str(issue.id))


async def delete_issue(session: AsyncSession, user, identifier: str, request_id: str | None) -> None:
    issue = await get_issue(session, identifier)
    if not issue:
        raise AppError("NOT_FOUND", "Ticket no encontrado", 404)
    await ensure_issue_visible(session, user, issue)
    # Solo administración global o PROJECT_MANAGER poseen issue.delete por defecto.
    # Mantenerlo como permiso explícito permite ampliar la política sin reescribir este servicio.
    await ensure_project_permission(session, user, issue.project_id, Permission.ISSUE_DELETE)

    issue.deleted_at = datetime.now(timezone.utc)
    issue.version += 1
    await record_audit(
        session, entity_type="issue", entity_id=issue.id, project_id=issue.project_id,
        action="ISSUE_DELETED", actor_user_id=user.id, old_value=issue.title, request_id=request_id,
    )
    await session.commit()
