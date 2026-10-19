from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AppError
from app.core.permissions import Permission, ensure_issue_participant, ensure_issue_visible, ensure_project_permission
from app.integrations.storage.s3 import (
    create_presigned_download,
    create_presigned_upload,
    delete_object,
    upload_image_bytes,
    validate_issue_storage_key,
    verify_uploaded_object,
)
from app.modules.issues.models import IssueImage
from app.modules.issues.repository import get_issue


def image_view(image: IssueImage) -> dict:
    """La BD guarda metadata; la URL se firma al responder y apunta al objeto privado en S3."""
    return {
        "id": str(image.id),
        "issue_id": str(image.issue_id),
        "filename": image.original_filename,
        "content_type": image.mime_type,
        "size_bytes": image.size_bytes,
        "caption": image.caption,
        "url": create_presigned_download(image.storage_key),
        "created_at": image.created_at.isoformat(),
    }


async def images_for_issues(session: AsyncSession, issue_ids: Iterable[UUID]) -> dict[UUID, list[IssueImage]]:
    ids = list(dict.fromkeys(issue_ids))
    if not ids:
        return {}
    rows = list((await session.scalars(
        select(IssueImage)
        .where(IssueImage.issue_id.in_(ids))
        .order_by(IssueImage.issue_id, IssueImage.created_at)
    )).all())
    grouped: dict[UUID, list[IssueImage]] = defaultdict(list)
    for row in rows:
        grouped[row.issue_id].append(row)
    return dict(grouped)


async def upload_image(
    session: AsyncSession,
    user,
    identifier: str,
    *,
    filename: str,
    content_type: str,
    content: bytes,
    caption: str | None,
    request_id: str | None,
) -> IssueImage:
    """Recibe la imagen en FastAPI, la sube a S3 y guarda solo metadata en PostgreSQL.

    No usa el navegador para hacer PUT a S3, por lo que no depende de CORS del bucket.
    """
    issue = await get_issue(session, identifier)
    if not issue:
        raise AppError("NOT_FOUND", "Ticket no encontrado", 404)
    await ensure_issue_participant(session, user, issue)
    await ensure_project_permission(session, user, issue.project_id, Permission.ATTACHMENT_UPLOAD)

    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    storage_key = await upload_image_bytes(issue.id, filename, normalized_type, content)
    image = IssueImage(
        issue_id=issue.id,
        storage_key=storage_key,
        original_filename=filename,
        mime_type=normalized_type,
        size_bytes=len(content),
        caption=caption.strip() if caption and caption.strip() else None,
        uploaded_by=user.id,
    )
    try:
        session.add(image)
        await session.flush()
        await record_audit(
            session,
            entity_type="issue",
            entity_id=issue.id,
            project_id=issue.project_id,
            action="IMAGE_ADDED",
            actor_user_id=user.id,
            metadata={"image_id": str(image.id), "filename": image.original_filename},
            request_id=request_id,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        try:
            await delete_object(storage_key)
        except Exception:
            pass
        raise
    return image


async def create_upload_url(session: AsyncSession, user, identifier: str, data) -> dict:
    issue = await get_issue(session, identifier)
    if not issue:
        raise AppError("NOT_FOUND", "Ticket no encontrado", 404)
    await ensure_issue_participant(session, user, issue)
    await ensure_project_permission(session, user, issue.project_id, Permission.ATTACHMENT_UPLOAD)
    ticket = create_presigned_upload(issue.id, data.filename, data.content_type, data.size_bytes)
    return {
        "storage_key": ticket.storage_key,
        "upload_url": ticket.upload_url,
        "headers": ticket.headers,
        "expires_in": ticket.expires_in,
    }


async def confirm_image(session: AsyncSession, user, identifier: str, data, request_id: str | None) -> IssueImage:
    issue = await get_issue(session, identifier)
    if not issue:
        raise AppError("NOT_FOUND", "Ticket no encontrado", 404)
    await ensure_issue_participant(session, user, issue)
    await ensure_project_permission(session, user, issue.project_id, Permission.ATTACHMENT_UPLOAD)
    validate_issue_storage_key(issue.id, data.storage_key)

    duplicate = await session.scalar(select(IssueImage.id).where(IssueImage.storage_key == data.storage_key))
    if duplicate:
        raise AppError("IMAGE_ALREADY_CONFIRMED", "La imagen ya fue agregada al ticket", 409)

    await verify_uploaded_object(data.storage_key, data.content_type, data.size_bytes)
    image = IssueImage(
        issue_id=issue.id,
        storage_key=data.storage_key,
        original_filename=data.filename,
        mime_type=data.content_type,
        size_bytes=data.size_bytes,
        caption=data.caption.strip() if data.caption else None,
        uploaded_by=user.id,
    )
    session.add(image)
    await session.flush()
    await record_audit(
        session,
        entity_type="issue",
        entity_id=issue.id,
        project_id=issue.project_id,
        action="IMAGE_ADDED",
        actor_user_id=user.id,
        metadata={"image_id": str(image.id), "filename": image.original_filename},
        request_id=request_id,
    )
    await session.commit()
    return image


async def list_images(session: AsyncSession, user, identifier: str) -> list[IssueImage]:
    issue = await get_issue(session, identifier)
    if not issue:
        raise AppError("NOT_FOUND", "Ticket no encontrado", 404)
    await ensure_issue_visible(session, user, issue)
    return list((await session.scalars(
        select(IssueImage).where(IssueImage.issue_id == issue.id).order_by(IssueImage.created_at)
    )).all())


async def remove_image(session: AsyncSession, user, identifier: str, image_id: UUID, request_id: str | None) -> None:
    issue = await get_issue(session, identifier)
    if not issue:
        raise AppError("NOT_FOUND", "Ticket no encontrado", 404)
    await ensure_issue_participant(session, user, issue)
    await ensure_project_permission(session, user, issue.project_id, Permission.ATTACHMENT_UPLOAD)
    image = await session.scalar(select(IssueImage).where(IssueImage.id == image_id, IssueImage.issue_id == issue.id))
    if not image:
        raise AppError("NOT_FOUND", "Imagen no encontrada", 404)

    # El objeto se elimina primero. Si S3 falla, la fila permanece para poder reintentar.
    await delete_object(image.storage_key)
    await record_audit(
        session,
        entity_type="issue",
        entity_id=issue.id,
        project_id=issue.project_id,
        action="IMAGE_REMOVED",
        actor_user_id=user.id,
        metadata={"image_id": str(image.id), "filename": image.original_filename},
        request_id=request_id,
    )
    await session.delete(image)
    await session.commit()
