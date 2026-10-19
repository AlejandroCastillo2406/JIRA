from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.core.permissions import (
    Permission,
    can_manage_project,
    ensure_issue_visible,
    ensure_project_permission,
)
from app.modules.issues.block_service import active_blocks_for_issues, list_block_history
from app.modules.issues.image_service import (
    confirm_image,
    create_upload_url,
    image_view,
    images_for_issues,
    list_images,
    remove_image,
    upload_image,
)
from app.modules.issues.repository import get_issue, list_project_issues
from app.modules.issues.schemas import (
    IssueCreate,
    IssueImageConfirm,
    IssueImageUploadRequest,
    IssueUpdate,
    RankMoveRequest,
    TransitionRequest,
)
from app.modules.issues.service import (
    create_issue,
    delete_issue,
    issue_view,
    move_rank,
    transition_issue,
    update_issue,
)

router = APIRouter(tags=["Issues"])


async def _issue_response(session: AsyncSession, issue):
    grouped = await images_for_issues(session, [issue.id])
    blocks = await active_blocks_for_issues(session, [issue.id])
    return issue_view(issue, grouped.get(issue.id, []), blocks.get(issue.id))


@router.get("/projects/{project_id}/issues")
async def issues_list(
    project_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_id: UUID | None = None,
    assignee_id: UUID | None = None,
    q: str | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    await ensure_project_permission(session, user, project_id, Permission.PROJECT_READ)
    manager = await can_manage_project(session, user, project_id)
    # Los miembros normales jamás pueden pedir tickets donde no participan cambiando el query string.
    effective_assignee = assignee_id if manager else None
    participant_id = None if manager else user.id
    rows, total = await list_project_issues(
        session,
        project_id,
        status_id=status_id,
        assignee_id=effective_assignee,
        participant_id=participant_id,
        q=q,
        page=page,
        page_size=page_size,
    )
    issue_ids = [row.id for row in rows]
    images = await images_for_issues(session, issue_ids)
    blocks = await active_blocks_for_issues(session, issue_ids)
    return {
        "data": [issue_view(row, images.get(row.id, []), blocks.get(row.id)) for row in rows],
        "pagination": {"page": page, "page_size": page_size, "total": total},
    }


@router.post("/projects/{project_id}/issues", status_code=201)
async def issue_create(
    project_id: UUID,
    payload: IssueCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    issue = await create_issue(session, user, project_id, payload, getattr(request.state, "request_id", None))
    return {"data": await _issue_response(session, issue)}


@router.get("/issues/{identifier}")
async def issue_detail(identifier: str, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    issue = await get_issue(session, identifier)
    if not issue:
        raise AppError("NOT_FOUND", "Ticket no encontrado", 404)
    await ensure_issue_visible(session, user, issue)
    return {"data": await _issue_response(session, issue)}


@router.patch("/issues/{identifier}")
async def issue_patch(
    identifier: str,
    payload: IssueUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    issue = await update_issue(session, user, identifier, payload, getattr(request.state, "request_id", None))
    return {"data": await _issue_response(session, issue)}


@router.delete("/issues/{identifier}", status_code=204)
async def issue_delete(
    identifier: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    await delete_issue(session, user, identifier, getattr(request.state, "request_id", None))


@router.post("/issues/{identifier}/transition")
async def issue_transition(
    identifier: str,
    payload: TransitionRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    issue = await transition_issue(session, user, identifier, payload, getattr(request.state, "request_id", None))
    return {"data": await _issue_response(session, issue)}


@router.patch("/issues/{identifier}/rank")
async def issue_rank(
    identifier: str,
    payload: RankMoveRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    issue = await move_rank(
        session,
        user,
        identifier,
        payload.before_issue_id,
        payload.after_issue_id,
        getattr(request.state, "request_id", None),
    )
    return {"data": await _issue_response(session, issue)}


@router.post("/issues/{identifier}/images/upload", status_code=201)
async def issue_image_upload(
    identifier: str,
    request: Request,
    file: UploadFile = File(...),
    caption: str | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    # Lee como máximo el límite configurado + 1 byte para poder rechazar archivos grandes
    # antes de intentar subirlos a S3. UploadFile usa archivo temporal para entradas grandes.
    from app.core.config import settings

    filename = file.filename or "image"
    content_type = file.content_type or "application/octet-stream"
    content = await file.read(settings.s3_max_image_bytes + 1)
    await file.close()
    image = await upload_image(
        session,
        user,
        identifier,
        filename=filename,
        content_type=content_type,
        content=content,
        caption=caption,
        request_id=getattr(request.state, "request_id", None),
    )
    return {"data": image_view(image)}


@router.post("/issues/{identifier}/images/upload-url")
async def issue_image_upload_url(
    identifier: str,
    payload: IssueImageUploadRequest,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    return {"data": await create_upload_url(session, user, identifier, payload)}


@router.post("/issues/{identifier}/images", status_code=201)
async def issue_image_confirm(
    identifier: str,
    payload: IssueImageConfirm,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    image = await confirm_image(session, user, identifier, payload, getattr(request.state, "request_id", None))
    return {"data": image_view(image)}


@router.get("/issues/{identifier}/images")
async def issue_images(identifier: str, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    return {"data": [image_view(row) for row in await list_images(session, user, identifier)]}


@router.get("/issues/{identifier}/blocks")
async def issue_blocks(identifier: str, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    """Historial de bloqueos del ticket, incluyendo el bloqueo activo si existe."""
    return {"data": await list_block_history(session, user, identifier)}


@router.delete("/issues/{identifier}/images/{image_id}", status_code=204)
async def issue_image_delete(
    identifier: str,
    image_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    await remove_image(session, user, identifier, image_id, getattr(request.state, "request_id", None))
