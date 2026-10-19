from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from pathlib import PurePath
from uuid import UUID, uuid4

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.core.exceptions import AppError


ALLOWED_IMAGE_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UploadTicket:
    storage_key: str
    upload_url: str
    headers: dict[str, str]
    expires_in: int


def _client():
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if settings.aws_session_token:
            kwargs["aws_session_token"] = settings.aws_session_token
    return boto3.client("s3", **kwargs)


def _require_bucket() -> str:
    if not settings.s3_bucket:
        raise AppError(
            "S3_NOT_CONFIGURED",
            "S3 no está configurado. Define S3_BUCKET y las credenciales AWS.",
            503,
        )
    return settings.s3_bucket


def validate_image_metadata(content_type: str, size_bytes: int) -> None:
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise AppError(
            "INVALID_IMAGE_TYPE",
            "Formato no permitido. Usa JPG, PNG o WEBP.",
            422,
            {"allowed": sorted(ALLOWED_IMAGE_TYPES)},
        )
    if size_bytes <= 0 or size_bytes > settings.s3_max_image_bytes:
        raise AppError(
            "INVALID_IMAGE_SIZE",
            f"La imagen debe pesar entre 1 byte y {settings.s3_max_image_bytes} bytes.",
            422,
            {"max_bytes": settings.s3_max_image_bytes},
        )


def build_storage_key(issue_id: UUID, original_filename: str, content_type: str) -> str:
    validate_image_metadata(content_type, 1)
    base = PurePath(original_filename).name or "image"
    safe = _SAFE_FILENAME.sub("-", base).strip(".-")[:80] or "image"
    stem = os.path.splitext(safe)[0][:60] or "image"
    extension = ALLOWED_IMAGE_TYPES[content_type]
    return f"issues/{issue_id}/{uuid4()}-{stem}{extension}"


def validate_issue_storage_key(issue_id: UUID, storage_key: str) -> None:
    prefix = f"issues/{issue_id}/"
    if not storage_key.startswith(prefix) or ".." in storage_key:
        raise AppError("INVALID_STORAGE_KEY", "La imagen no pertenece a este ticket", 422)


def create_presigned_upload(issue_id: UUID, original_filename: str, content_type: str, size_bytes: int) -> UploadTicket:
    bucket = _require_bucket()
    validate_image_metadata(content_type, size_bytes)
    key = build_storage_key(issue_id, original_filename, content_type)
    try:
        url = _client().generate_presigned_url(
            "put_object",
            Params={
                "Bucket": bucket,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=settings.s3_presign_expiry_seconds,
        )
    except (BotoCoreError, ClientError) as exc:
        raise AppError("S3_PRESIGN_FAILED", "No fue posible preparar la carga de la imagen", 502) from exc
    return UploadTicket(
        storage_key=key,
        upload_url=url,
        headers={"Content-Type": content_type},
        expires_in=settings.s3_presign_expiry_seconds,
    )


def create_presigned_download(storage_key: str) -> str:
    bucket = _require_bucket()
    try:
        return _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": storage_key},
            ExpiresIn=settings.s3_presign_expiry_seconds,
        )
    except (BotoCoreError, ClientError) as exc:
        raise AppError("S3_PRESIGN_FAILED", "No fue posible abrir la imagen", 502) from exc


async def upload_image_bytes(issue_id: UUID, original_filename: str, content_type: str, content: bytes) -> str:
    """Sube una imagen a S3 desde el backend y devuelve únicamente su storage_key.

    Este flujo evita que el navegador necesite CORS contra S3. PostgreSQL sigue
    guardando solo metadata y nunca los bytes de la imagen.
    """
    bucket = _require_bucket()
    size_bytes = len(content)
    validate_image_metadata(content_type, size_bytes)
    key = build_storage_key(issue_id, original_filename, content_type)

    def _put():
        return _client().put_object(
            Bucket=bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
        )

    try:
        response = await asyncio.to_thread(_put)
        metadata = response.get("ResponseMetadata", {}) if isinstance(response, dict) else {}
        logger.info(
            "[S3] Imagen cargada | bucket=%s key=%s content_type=%s size_bytes=%s request_id=%s http_status=%s",
            bucket,
            key,
            content_type,
            size_bytes,
            metadata.get("RequestId"),
            metadata.get("HTTPStatusCode"),
        )
    except ClientError as exc:
        error = exc.response.get("Error", {})
        metadata = exc.response.get("ResponseMetadata", {})
        logger.exception(
            "[S3] AWS rechazó la carga | bucket=%s key=%s code=%s message=%s request_id=%s http_status=%s",
            bucket,
            key,
            error.get("Code"),
            error.get("Message"),
            metadata.get("RequestId"),
            metadata.get("HTTPStatusCode"),
        )
        raise AppError("S3_UPLOAD_FAILED", "No fue posible subir la imagen a S3", 502) from exc
    except BotoCoreError as exc:
        logger.exception(
            "[S3] Error de boto3 al subir | bucket=%s key=%s error_type=%s error=%s",
            bucket,
            key,
            type(exc).__name__,
            str(exc),
        )
        raise AppError("S3_UPLOAD_FAILED", "No fue posible subir la imagen a S3", 502) from exc
    return key


async def verify_uploaded_object(storage_key: str, content_type: str, size_bytes: int) -> None:
    bucket = _require_bucket()
    validate_image_metadata(content_type, size_bytes)

    def _head():
        return _client().head_object(Bucket=bucket, Key=storage_key)

    try:
        metadata = await asyncio.to_thread(_head)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            raise AppError("IMAGE_NOT_UPLOADED", "La imagen aún no existe en S3", 422) from exc
        raise AppError("S3_VERIFY_FAILED", "No fue posible verificar la imagen en S3", 502) from exc
    except BotoCoreError as exc:
        raise AppError("S3_VERIFY_FAILED", "No fue posible verificar la imagen en S3", 502) from exc

    actual_size = int(metadata.get("ContentLength") or 0)
    actual_type = str(metadata.get("ContentType") or "").split(";", 1)[0].strip().lower()
    if actual_size != size_bytes:
        raise AppError(
            "IMAGE_SIZE_MISMATCH",
            "El tamaño confirmado no coincide con el archivo almacenado.",
            422,
            {"expected": size_bytes, "actual": actual_size},
        )
    if actual_type != content_type:
        raise AppError(
            "IMAGE_TYPE_MISMATCH",
            "El tipo confirmado no coincide con el archivo almacenado.",
            422,
            {"expected": content_type, "actual": actual_type},
        )


async def delete_object(storage_key: str) -> None:
    bucket = _require_bucket()

    def _delete():
        _client().delete_object(Bucket=bucket, Key=storage_key)

    try:
        await asyncio.to_thread(_delete)
    except (BotoCoreError, ClientError) as exc:
        raise AppError("S3_DELETE_FAILED", "No fue posible eliminar la imagen de S3", 502) from exc
