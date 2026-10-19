from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.database import get_session
from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.auth.schemas import AuthResponse, LoginRequest
from app.modules.auth.service import login, logout, refresh_access

router = APIRouter(prefix="/auth", tags=["Auth"])


def _set_refresh_cookie(response: Response, token: str) -> None:
    # Cross-origin (S3/CloudFront → API): browsers only send the cookie with
    # credentials if SameSite=None and Secure. Same-origin/local keeps Lax.
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="none" if settings.cookie_secure else "lax",
        max_age=settings.refresh_token_days * 86400,
        path=f"{settings.api_v1_prefix}/auth",
    )


@router.post("/login", response_model=AuthResponse)
async def login_endpoint(payload: LoginRequest, request: Request, response: Response,
                         session: AsyncSession = Depends(get_session)):
    data, refresh = await login(session, payload.email, payload.password, request)
    _set_refresh_cookie(response, refresh)
    return data


@router.post("/refresh", response_model=AuthResponse)
async def refresh_endpoint(response: Response, refresh_token: str | None = Cookie(default=None),
                           session: AsyncSession = Depends(get_session)):
    if not refresh_token:
        raise AppError("NO_REFRESH_TOKEN", "No hay sesión activa", 401)
    data, new_refresh = await refresh_access(session, refresh_token)
    _set_refresh_cookie(response, new_refresh)
    return data


@router.post("/logout", status_code=204)
async def logout_endpoint(response: Response, refresh_token: str | None = Cookie(default=None),
                          session: AsyncSession = Depends(get_session)):
    await logout(session, refresh_token)
    response.delete_cookie("refresh_token", path=f"{settings.api_v1_prefix}/auth")


@router.get("/me")
async def me_endpoint(user=Depends(get_current_user)):
    return {"data": {
        "id": str(user.id), "email": user.email, "display_name": user.display_name,
        "timezone": user.timezone, "locale": user.locale, "global_role": user.global_role.code,
    }}
