from uuid import UUID
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.exceptions import AppError
from app.core.security import decode_access_token
from app.modules.users.models import User
from app.modules.auth.models import UserSession

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not credentials:
        raise AppError("UNAUTHORIZED", "Autenticación requerida", 401)
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = UUID(payload["sub"])
        session_id = UUID(payload["sid"])
    except Exception as exc:
        raise AppError("INVALID_TOKEN", "Token inválido o vencido", 401) from exc

    db_session = await session.scalar(select(UserSession).where(UserSession.id == session_id))
    if not db_session or db_session.revoked_at is not None:
        raise AppError("SESSION_REVOKED", "La sesión ya no es válida", 401)
    user = await session.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
    if not user:
        raise AppError("UNAUTHORIZED", "Usuario no disponible", 401)
    return user
