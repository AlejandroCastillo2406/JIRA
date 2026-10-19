from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.deps import get_current_user
from app.modules.users.schemas import UserCreate
from app.modules.users.service import create_user, list_project_roles, list_users, user_view

router = APIRouter(tags=["Users"])


@router.get("/users")
async def users(session: AsyncSession = Depends(get_session), current=Depends(get_current_user)):
    return {"data": [user_view(x) for x in await list_users(session, current)]}


@router.post("/users", status_code=201)
async def user_create(payload: UserCreate, session: AsyncSession = Depends(get_session), current=Depends(get_current_user)):
    return {"data": user_view(await create_user(session, current, payload))}


@router.get("/project-roles")
async def project_roles(session: AsyncSession = Depends(get_session), current=Depends(get_current_user)):
    rows = await list_project_roles(session)
    return {"data": [{"code": r.code, "name": r.name} for r in rows]}
