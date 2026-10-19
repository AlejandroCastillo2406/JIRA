from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import AppError
from app.core.security import hash_password
from app.modules.users.models import Role, User


async def ensure_global_admin(session: AsyncSession, user) -> None:
    role = await session.scalar(select(Role).where(Role.id == user.global_role_id))
    if not role or role.code not in {"SUPER_ADMIN", "ADMIN"}:
        raise AppError("FORBIDDEN", "Solo administración puede gestionar usuarios", 403)


def user_view(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "global_role": user.global_role.code,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat(),
    }


async def list_users(session: AsyncSession, current) -> list[User]:
    await ensure_global_admin(session, current)
    return list((await session.scalars(select(User).order_by(User.display_name))).all())


async def create_user(session: AsyncSession, current, data) -> User:
    await ensure_global_admin(session, current)
    email = data.email.lower()
    if await session.scalar(select(User.id).where(User.email == email)):
        raise AppError("EMAIL_EXISTS", "Ya existe un usuario con ese correo", 409)
    role = await session.scalar(select(Role).where(Role.code == data.global_role_code, Role.scope == "GLOBAL"))
    if not role:
        raise AppError("INVALID_ROLE", "Rol global inválido", 422)
    user = User(
        email=email,
        password_hash=hash_password(data.password),
        display_name=data.display_name,
        global_role_id=role.id,
        global_role=role,
        timezone="America/Mexico_City",
        locale="es-MX",
    )
    session.add(user)
    await session.commit()
    return user


async def list_project_roles(session: AsyncSession) -> list[Role]:
    return list((await session.scalars(
        select(Role).where(Role.scope == "PROJECT").order_by(Role.name)
    )).all())
