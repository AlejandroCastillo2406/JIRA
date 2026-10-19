import asyncio

from sqlalchemy import delete, insert, select

from app.core.config import settings
from app.core.database import SessionLocal, get_engine
from app.core.permissions import Permission
from app.core.security import hash_password
import app.models  # noqa: F401
from app.modules.users.models import PermissionModel, Role, User, role_permissions
from app.modules.workflows.models import IssueType, Priority, Workflow, WorkflowStatus, WorkflowTransition


ROLE_PERMISSIONS = {
    "PROJECT_MANAGER": [p.value for p in Permission],
    "DEVELOPER": [
        Permission.PROJECT_READ.value,
        Permission.ISSUE_PROGRESS.value,
        Permission.COMMENT_CREATE.value,
        Permission.ATTACHMENT_UPLOAD.value,
    ],
    "REVIEWER": [
        Permission.PROJECT_READ.value,
        Permission.COMMENT_CREATE.value,
        Permission.ATTACHMENT_UPLOAD.value,
        Permission.VALIDATION_DECIDE.value,
    ],
    "PROJECT_VIEWER": [Permission.PROJECT_READ.value],
}


# El workflow por defecto es intencionalmente estricto:
# - administración/PROJECT_MANAGER mueve backlog -> por hacer, si hiciera falta;
# - DEVELOPER avanza el trabajo hasta "Listo para validar";
# - REVIEWER es quien valida y mueve "Listo para validar" -> "Terminado".
# Se conservan transiciones de bloqueo para el trabajo del developer.
DEFAULT_TRANSITION_SPECS = [
    ("BACKLOG", "TODO", Permission.ISSUE_ASSIGN.value),
    ("TODO", "IN_PROGRESS", Permission.ISSUE_PROGRESS.value),
    ("IN_PROGRESS", "TODO", Permission.ISSUE_PROGRESS.value),
    ("IN_PROGRESS", "BLOCKED", Permission.ISSUE_PROGRESS.value),
    ("BLOCKED", "IN_PROGRESS", Permission.ISSUE_PROGRESS.value),
    ("BLOCKED", "TODO", Permission.ISSUE_PROGRESS.value),
    ("IN_PROGRESS", "READY_FOR_TESTING", Permission.ISSUE_PROGRESS.value),
    # El Developer puede retirar su entrega de validación y regresarla a trabajo.
    ("READY_FOR_TESTING", "IN_PROGRESS", Permission.ISSUE_PROGRESS.value),
    ("READY_FOR_TESTING", "TODO", Permission.ISSUE_PROGRESS.value),
    # Solo Reviewer (o administración) dispone de validation.decide.
    ("READY_FOR_TESTING", "DONE", Permission.VALIDATION_DECIDE.value),
]


async def bootstrap():
    async with SessionLocal(bind=get_engine()) as session:
        try:
            permission_rows = {}
            for perm in Permission:
                row = await session.scalar(select(PermissionModel).where(PermissionModel.code == perm.value))
                if not row:
                    row = PermissionModel(code=perm.value, description=perm.value)
                    session.add(row)
                    await session.flush()
                permission_rows[perm.value] = row

            role_specs = [
                ("SUPER_ADMIN", "Super Admin", "GLOBAL"),
                ("ADMIN", "Admin", "GLOBAL"),
                ("MEMBER", "Miembro", "GLOBAL"),
                ("VIEWER", "Visor", "GLOBAL"),
                ("PROJECT_MANAGER", "Project Manager", "PROJECT"),
                ("DEVELOPER", "Desarrollador", "PROJECT"),
                ("REVIEWER", "Revisor", "PROJECT"),
                ("PROJECT_VIEWER", "Visor de proyecto", "PROJECT"),
            ]
            roles = {}
            for code, name, scope in role_specs:
                role = await session.scalar(select(Role).where(Role.code == code))
                if not role:
                    role = Role(code=code, name=name, scope=scope)
                    session.add(role)
                    await session.flush()
                roles[code] = role

            # No asignar role.permissions: con AsyncSession puede disparar lazy loading/MissingGreenlet.
            for role_code, permission_codes in ROLE_PERMISSIONS.items():
                role = roles[role_code]
                await session.execute(delete(role_permissions).where(role_permissions.c.role_id == role.id))
                if permission_codes:
                    await session.execute(
                        insert(role_permissions),
                        [
                            {"role_id": role.id, "permission_id": permission_rows[permission_code].id}
                            for permission_code in permission_codes
                        ],
                    )

            issue_types = [
                ("EPIC", "Épica", True, False, 10),
                ("STORY", "Historia", False, False, 20),
                ("TASK", "Tarea", False, False, 30),
                ("BUG", "Error", False, False, 40),
                ("SUBTASK", "Subtarea", False, True, 50),
            ]
            for code, name, epic, subtask, pos in issue_types:
                row = await session.scalar(select(IssueType).where(IssueType.project_id.is_(None), IssueType.code == code))
                if not row:
                    session.add(IssueType(project_id=None, code=code, name=name, is_epic=epic,
                                          is_subtask=subtask, position=pos))

            priorities = [
                ("URGENT", "Urgente", 1, "#dc2626"),
                ("HIGH", "Alta", 2, "#ea580c"),
                ("MEDIUM", "Media", 3, "#ca8a04"),
                ("LOW", "Baja", 4, "#64748b"),
            ]
            for code, name, rank, color in priorities:
                row = await session.scalar(select(Priority).where(Priority.project_id.is_(None), Priority.code == code))
                if not row:
                    session.add(Priority(project_id=None, code=code, name=name, rank=rank, color=color))

            workflow = await session.scalar(select(Workflow).where(Workflow.project_id.is_(None), Workflow.name == "Default"))
            if not workflow:
                workflow = Workflow(project_id=None, name="Default")
                session.add(workflow)
                await session.flush()

            status_specs = [
                ("BACKLOG", "Backlog", "TODO", 10, "#64748b", False),
                ("TODO", "Por hacer", "TODO", 20, "#475569", True),
                ("IN_PROGRESS", "En progreso", "IN_PROGRESS", 30, "#2563eb", False),
                ("BLOCKED", "Bloqueado", "IN_PROGRESS", 40, "#dc2626", False),
                ("READY_FOR_TESTING", "Listo para validar", "IN_PROGRESS", 50, "#7c3aed", False),
                ("DONE", "Terminado", "DONE", 60, "#16a34a", False),
            ]
            statuses_by_code = {}
            for code, name, category, pos, color, initial in status_specs:
                status = await session.scalar(select(WorkflowStatus).where(
                    WorkflowStatus.workflow_id == workflow.id, WorkflowStatus.code == code
                ))
                if not status:
                    status = WorkflowStatus(
                        workflow_id=workflow.id, code=code, name=name, category=category,
                        position=pos, color=color, is_initial=initial,
                    )
                    session.add(status)
                    await session.flush()
                else:
                    # Bootstrap es idempotente y también corrige instalaciones existentes.
                    status.name = name
                    status.category = category
                    status.position = pos
                    status.color = color
                    status.is_initial = initial
                statuses_by_code[code] = status

            # El bootstrap anterior generaba todas las combinaciones posibles.
            # Eliminamos únicamente las transiciones del workflow Default y recreamos
            # la política explícita para que la autorización se aplique también a BD existentes.
            await session.execute(
                delete(WorkflowTransition).where(WorkflowTransition.workflow_id == workflow.id)
            )
            for source_code, target_code, required_permission in DEFAULT_TRANSITION_SPECS:
                session.add(WorkflowTransition(
                    workflow_id=workflow.id,
                    from_status_id=statuses_by_code[source_code].id,
                    to_status_id=statuses_by_code[target_code].id,
                    required_permission=required_permission,
                ))

            admin = await session.scalar(select(User).where(User.email == settings.bootstrap_admin_email.lower()))
            if not admin:
                session.add(User(
                    email=settings.bootstrap_admin_email.lower(),
                    password_hash=hash_password(settings.bootstrap_admin_password),
                    display_name=settings.bootstrap_admin_name,
                    global_role_id=roles["SUPER_ADMIN"].id,
                    timezone="America/Mexico_City",
                    locale="es-MX",
                ))

            await session.commit()
            print("Bootstrap completado")
        except Exception:
            await session.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(bootstrap())
