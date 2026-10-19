from datetime import datetime, timedelta, timezone
from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.security import create_access_token, hash_refresh_token, new_refresh_token, verify_password
from app.modules.auth.models import UserSession
from app.modules.users.models import User


def _user_view(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "timezone": user.timezone,
        "locale": user.locale,
        "global_role": user.global_role.code,
    }


async def login(session: AsyncSession, email: str, password: str, request: Request) -> tuple[dict, str]:
    user = await session.scalar(select(User).options(joinedload(User.global_role)).where(User.email == email.lower()))
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        raise AppError("INVALID_CREDENTIALS", "Correo o contraseña incorrectos", 401)

    refresh = new_refresh_token()
    db_session = UserSession(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_days),
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    user.last_login_at = datetime.now(timezone.utc)
    session.add(db_session)
    await session.flush()
    await session.commit()
    access = create_access_token(str(user.id), str(db_session.id))
    return {"access_token": access, "token_type": "bearer", "user": _user_view(user)}, refresh


async def refresh_access(session: AsyncSession, raw_refresh: str) -> tuple[dict, str]:
    token_hash = hash_refresh_token(raw_refresh)
    current = await session.scalar(select(UserSession).where(UserSession.refresh_token_hash == token_hash))
    now = datetime.now(timezone.utc)
    if not current:
        raise AppError("INVALID_REFRESH_TOKEN", "Sesión inválida", 401)
    if current.revoked_at is not None:
        await session.execute(update(UserSession).where(UserSession.family_id == current.family_id).values(revoked_at=now))
        await session.commit()
        raise AppError("REFRESH_REUSE_DETECTED", "La sesión fue revocada por seguridad", 401)
    if current.expires_at <= now:
        current.revoked_at = now
        await session.commit()
        raise AppError("REFRESH_EXPIRED", "La sesión venció", 401)

    user = await session.scalar(select(User).options(joinedload(User.global_role)).where(User.id == current.user_id, User.is_active.is_(True)))
    if not user:
        raise AppError("UNAUTHORIZED", "Usuario no disponible", 401)

    new_raw = new_refresh_token()
    replacement = UserSession(
        user_id=current.user_id,
        family_id=current.family_id,
        refresh_token_hash=hash_refresh_token(new_raw),
        expires_at=now + timedelta(days=settings.refresh_token_days),
        user_agent=current.user_agent,
        ip=current.ip,
    )
    session.add(replacement)
    await session.flush()
    current.revoked_at = now
    current.replaced_by = replacement.id
    await session.commit()
    access = create_access_token(str(user.id), str(replacement.id))
    return {"access_token": access, "token_type": "bearer", "user": _user_view(user)}, new_raw


async def logout(session: AsyncSession, raw_refresh: str | None) -> None:
    if not raw_refresh:
        return
    token_hash = hash_refresh_token(raw_refresh)
    db_session = await session.scalar(select(UserSession).where(UserSession.refresh_token_hash == token_hash))
    if db_session and db_session.revoked_at is None:
        db_session.revoked_at = datetime.now(timezone.utc)
        await session.commit()
