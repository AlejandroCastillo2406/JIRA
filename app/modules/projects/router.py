from uuid import UUID
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.deps import get_current_user
from app.modules.projects.member_schemas import ProjectMemberAdd, ProjectMemberUpdate
from app.modules.projects.schemas import ProjectCreate
from app.modules.projects.service import (
    add_project_member,
    create_project,
    delete_project,
    delete_project_member,
    get_project,
    list_available_project_members,
    list_project_members,
    list_projects,
    member_view,
    update_project_member,
)

router = APIRouter(tags=["Projects"])


def _view(p):
    return {
        "id": str(p.id),
        "key": p.key,
        "name": p.name,
        "description": p.description,
        "status": p.status,
        "lead_user_id": str(p.lead_user_id),
        "created_at": p.created_at.isoformat(),
    }


@router.get("/projects")
async def projects(session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    return {"data": [_view(p) for p in await list_projects(session, user)]}


@router.post("/projects", status_code=201)
async def project_create(payload: ProjectCreate, request: Request, session: AsyncSession = Depends(get_session),
                         user=Depends(get_current_user)):
    project = await create_project(session, user, payload, getattr(request.state, "request_id", None))
    return {"data": _view(project)}


@router.get("/projects/{identifier}")
async def project_detail(identifier: str, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    return {"data": _view(await get_project(session, user, identifier))}




@router.delete("/projects/{identifier}", status_code=204)
async def project_delete(identifier: str, request: Request, session: AsyncSession = Depends(get_session),
                         user=Depends(get_current_user)):
    await delete_project(session, user, identifier, getattr(request.state, "request_id", None))


@router.get("/projects/{project_id}/members")
async def project_members(project_id: UUID, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    return {"data": [member_view(m) for m in await list_project_members(session, user, project_id)]}


@router.get("/projects/{project_id}/available-members")
async def project_available_members(project_id: UUID, session: AsyncSession = Depends(get_session),
                                    user=Depends(get_current_user)):
    rows = await list_available_project_members(session, user, project_id)
    return {
        "data": [
            {
                "id": str(row.id),
                "display_name": row.display_name,
                "email": row.email,
                "global_role": row.global_role.code,
                "is_active": row.is_active,
            }
            for row in rows
        ]
    }


@router.post("/projects/{project_id}/members", status_code=201)
async def project_member_add(project_id: UUID, payload: ProjectMemberAdd,
                             session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    return {"data": member_view(await add_project_member(session, user, project_id, payload))}


@router.patch("/projects/{project_id}/members/{member_user_id}")
async def project_member_update(project_id: UUID, member_user_id: UUID, payload: ProjectMemberUpdate,
                                session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    await update_project_member(session, user, project_id, member_user_id, payload)
    return {"data": {"ok": True}}


@router.delete("/projects/{project_id}/members/{member_user_id}", status_code=204)
async def project_member_delete(project_id: UUID, member_user_id: UUID,
                                session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    await delete_project_member(session, user, project_id, member_user_id)
