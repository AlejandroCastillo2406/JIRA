from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AppError
from app.core.permissions import Permission, ensure_project_manager, ensure_project_permission
from app.integrations.email.ses import send_project_membership_email
from app.modules.issues.models import Issue
from app.modules.projects.models import Project, ProjectMember
from app.modules.users.models import Role
from app.modules.workflows.models import Workflow


async def list_projects(session: AsyncSession, user) -> list[Project]:
    role = await session.scalar(select(Role).where(Role.id == user.global_role_id))
    stmt = select(Project).where(Project.status == "ACTIVE").order_by(Project.created_at.desc())
    if not role or role.code not in {"SUPER_ADMIN", "ADMIN"}:
        stmt = stmt.join(ProjectMember, ProjectMember.project_id == Project.id).where(ProjectMember.user_id == user.id)
    return list((await session.scalars(stmt)).all())


async def create_project(session: AsyncSession, user, data, request_id: str | None) -> Project:
    exists = await session.scalar(select(Project.id).where(Project.key == data.key))
    if exists:
        raise AppError("PROJECT_KEY_EXISTS", "La clave del proyecto ya existe", 409)
    workflow = await session.scalar(select(Workflow).where(Workflow.project_id.is_(None), Workflow.name == "Default"))
    pm_role = await session.scalar(select(Role).where(Role.code == "PROJECT_MANAGER"))
    if not workflow or not pm_role:
        raise AppError("BOOTSTRAP_REQUIRED", "Faltan catálogos iniciales. Ejecuta bootstrap.", 500)
    project = Project(
        key=data.key, name=data.name, description=data.description, lead_user_id=user.id,
        created_by=user.id, default_workflow_id=workflow.id,
    )
    session.add(project)
    await session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=user.id, role_id=pm_role.id))
    await record_audit(session, entity_type="project", entity_id=project.id, project_id=project.id,
                       action="PROJECT_CREATED", actor_user_id=user.id, new_value=project.name, request_id=request_id)
    await session.commit()
    return project


async def get_project(session: AsyncSession, user, identifier: str) -> Project:
    try:
        project_uuid = UUID(identifier)
        clause = or_(Project.id == project_uuid, Project.key == identifier.upper())
    except ValueError:
        clause = Project.key == identifier.upper()
    project = await session.scalar(select(Project).where(clause, Project.status == "ACTIVE"))
    if not project:
        raise AppError("NOT_FOUND", "Proyecto no encontrado", 404)
    await ensure_project_permission(session, user, project.id, Permission.PROJECT_READ)
    return project


def member_view(membership: ProjectMember) -> dict:
    return {
        "user_id": str(membership.user_id),
        "display_name": membership.user.display_name,
        "email": membership.user.email,
        "role": membership.role.code,
    }


async def list_project_members(session: AsyncSession, user, project_id: UUID) -> list[ProjectMember]:
    await ensure_project_permission(session, user, project_id, Permission.PROJECT_READ)
    return list((await session.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project_id)
    )).all())


async def list_available_project_members(session: AsyncSession, user, project_id: UUID):
    """Usuarios activos que todavía no pertenecen al proyecto.

    Solo quien puede administrar miembros del proyecto puede consultar este directorio.
    Evita obligar al frontend a conocer/escribir correos manualmente y evita exponer
    el directorio completo a miembros sin permiso de actualización del proyecto.
    """
    from app.modules.users.models import User

    await ensure_project_permission(session, user, project_id, Permission.PROJECT_UPDATE)

    member_ids = select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
    stmt = (
        select(User)
        .where(User.is_active.is_(True), User.id.not_in(member_ids))
        .order_by(User.display_name, User.email)
    )
    return list((await session.scalars(stmt)).all())


async def add_project_member(session: AsyncSession, user, project_id: UUID, data) -> ProjectMember:
    from app.modules.users.models import User

    await ensure_project_permission(session, user, project_id, Permission.PROJECT_UPDATE)
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.status == "ACTIVE"))
    if not project:
        raise AppError("NOT_FOUND", "Proyecto no encontrado", 404)
    if data.user_id:
        target = await session.scalar(select(User).where(User.id == data.user_id, User.is_active.is_(True)))
    else:
        target = await session.scalar(select(User).where(User.email == data.email.lower(), User.is_active.is_(True)))
    if not target:
        raise AppError("USER_NOT_FOUND", "No existe un usuario activo con esa referencia", 404)
    role = await session.scalar(select(Role).where(Role.code == data.role_code, Role.scope == "PROJECT"))
    if not role:
        raise AppError("INVALID_ROLE", "Rol de proyecto inválido", 422)
    existing = await session.scalar(select(ProjectMember).where(
        ProjectMember.project_id == project_id, ProjectMember.user_id == target.id
    ))
    if existing:
        raise AppError("MEMBER_EXISTS", "El usuario ya pertenece al proyecto", 409)

    membership = ProjectMember(project_id=project_id, user_id=target.id, role_id=role.id, role=role, user=target)
    session.add(membership)
    await session.flush()

    # SES directo. Si SES está habilitado, no se confirma la membresía hasta que SES acepte el correo.
    await send_project_membership_email(
        to_email=target.email,
        display_name=target.display_name,
        project_key=project.key,
        project_name=project.name,
        role_name=role.name,
    )
    await session.commit()
    return membership


async def update_project_member(session: AsyncSession, user, project_id: UUID, member_user_id: UUID, data) -> None:
    await ensure_project_permission(session, user, project_id, Permission.PROJECT_UPDATE)
    membership = await session.scalar(select(ProjectMember).where(
        ProjectMember.project_id == project_id, ProjectMember.user_id == member_user_id
    ))
    if not membership:
        raise AppError("NOT_FOUND", "Miembro no encontrado", 404)
    role = await session.scalar(select(Role).where(Role.code == data.role_code, Role.scope == "PROJECT"))
    if not role:
        raise AppError("INVALID_ROLE", "Rol de proyecto inválido", 422)
    if membership.role_id == role.id:
        return

    project = await session.scalar(select(Project).where(Project.id == project_id))
    from app.modules.users.models import User
    target = await session.scalar(select(User).where(User.id == member_user_id))
    membership.role_id = role.id
    await session.flush()
    if project and target:
        await send_project_membership_email(
            to_email=target.email,
            display_name=target.display_name,
            project_key=project.key,
            project_name=project.name,
            role_name=role.name,
            changed=True,
        )
    await session.commit()


async def delete_project_member(session: AsyncSession, user, project_id: UUID, member_user_id: UUID) -> None:
    await ensure_project_permission(session, user, project_id, Permission.PROJECT_UPDATE)
    membership = await session.scalar(select(ProjectMember).where(
        ProjectMember.project_id == project_id, ProjectMember.user_id == member_user_id
    ))
    if not membership:
        raise AppError("NOT_FOUND", "Miembro no encontrado", 404)
    if member_user_id == user.id:
        raise AppError("CANNOT_REMOVE_SELF", "No puedes eliminarte a ti mismo del proyecto", 422)

    project = await session.scalar(select(Project).where(Project.id == project_id))
    if project and project.lead_user_id == member_user_id:
        raise AppError(
            "CANNOT_REMOVE_PROJECT_LEAD",
            "No puedes eliminar al responsable principal del proyecto sin cambiar primero el responsable.",
            422,
        )

    # Al sacar a una persona del proyecto no dejamos tickets apuntando a un usuario sin membresía.
    await session.execute(
        update(Issue)
        .where(Issue.project_id == project_id, Issue.assignee_id == member_user_id, Issue.deleted_at.is_(None))
        .values(assignee_id=None, version=Issue.version + 1)
    )
    await session.execute(
        update(Issue)
        .where(Issue.project_id == project_id, Issue.reviewer_id == member_user_id, Issue.deleted_at.is_(None))
        .values(reviewer_id=None, version=Issue.version + 1)
    )
    await session.delete(membership)
    await session.commit()


async def delete_project(session: AsyncSession, user, identifier: str, request_id: str | None) -> None:
    project = await get_project(session, user, identifier)
    await ensure_project_manager(session, user, project.id)
    project.status = "ARCHIVED"
    project.archived_at = datetime.now(timezone.utc)
    await record_audit(
        session, entity_type="project", entity_id=project.id, project_id=project.id,
        action="PROJECT_DELETED", actor_user_id=user.id, old_value=project.name, request_id=request_id,
    )
    await session.commit()
