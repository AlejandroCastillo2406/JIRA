from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppError


class Permission(StrEnum):
    PROJECT_READ = "project.read"
    PROJECT_UPDATE = "project.update"
    ISSUE_CREATE = "issue.create"
    ISSUE_UPDATE = "issue.update"
    ISSUE_ASSIGN = "issue.assign"
    ISSUE_PROGRESS = "issue.progress"
    ISSUE_DELETE = "issue.delete"
    COMMENT_CREATE = "comment.create"
    SPRINT_MANAGE = "sprint.manage"
    ATTACHMENT_UPLOAD = "attachment.upload"
    VALIDATION_DECIDE = "validation.decide"


def global_role_code(user) -> str | None:
    role = getattr(user, "global_role", None)
    return getattr(role, "code", None)


def is_global_admin(user) -> bool:
    return global_role_code(user) in {"SUPER_ADMIN", "ADMIN"}


async def get_project_membership(session: AsyncSession, user, project_id):
    from app.modules.projects.models import ProjectMember
    from app.modules.users.models import Role

    return await session.scalar(
        select(ProjectMember)
        .options(selectinload(ProjectMember.role).selectinload(Role.permissions))
        .where(ProjectMember.project_id == project_id, ProjectMember.user_id == user.id)
    )


async def ensure_project_permission(session: AsyncSession, user, project_id, permission: Permission) -> None:
    from app.modules.projects.models import Project

    active_project = await session.scalar(
        select(Project.id).where(Project.id == project_id, Project.status == "ACTIVE")
    )
    if not active_project:
        raise AppError("NOT_FOUND", "Recurso no encontrado", 404)

    if is_global_admin(user):
        return

    membership = await get_project_membership(session, user, project_id)
    if not membership:
        # 404 evita revelar proyectos a usuarios que no pertenecen a ellos.
        raise AppError("NOT_FOUND", "Recurso no encontrado", 404)

    allowed = {p.code for p in membership.role.permissions}
    if permission.value not in allowed:
        raise AppError("FORBIDDEN", "No tienes permiso para realizar esta acción", 403)


async def can_manage_project(session: AsyncSession, user, project_id) -> bool:
    """Administración global o PROJECT_MANAGER ven y administran todos los tickets del proyecto."""
    if is_global_admin(user):
        return True
    membership = await get_project_membership(session, user, project_id)
    return bool(membership and membership.role.code == "PROJECT_MANAGER")


async def ensure_project_manager(session: AsyncSession, user, project_id) -> None:
    if not await can_manage_project(session, user, project_id):
        raise AppError("FORBIDDEN", "Solo administración puede gestionar esta acción del proyecto", 403)


async def ensure_issue_visible(session: AsyncSession, user, issue) -> None:
    """Todo miembro con acceso de lectura al proyecto puede abrir el detalle del ticket.

    La visibilidad del tablero puede seguir siendo personal para Developer/Reviewer, pero
    si un integrante del proyecto conoce o recibe el enlace del ticket puede consultar
    su detalle. Usuarios ajenos al proyecto siguen recibiendo 404 por PROJECT_READ.
    """
    await ensure_project_permission(session, user, issue.project_id, Permission.PROJECT_READ)




async def ensure_issue_participant(session: AsyncSession, user, issue) -> None:
    """Escritura operativa solo para responsable/revisor o administración.

    Leer el detalle es más amplio, pero comentar/subir evidencia requiere participar
    explícitamente en el ticket.
    """
    await ensure_issue_visible(session, user, issue)
    if await can_manage_project(session, user, issue.project_id):
        return
    if issue.assignee_id != user.id and issue.reviewer_id != user.id:
        raise AppError("FORBIDDEN", "Solo participantes del ticket pueden realizar esta acción", 403)

async def ensure_issue_update(session: AsyncSession, user, issue) -> None:
    """Editar campos del ticket está reservado a administración/PROJECT_MANAGER."""
    await ensure_issue_visible(session, user, issue)
    await ensure_project_manager(session, user, issue.project_id)
