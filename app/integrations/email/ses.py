from __future__ import annotations

import asyncio
import logging
from html import escape

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)


def _mask_access_key(value: str | None) -> str:
    if not value:
        return "NO_CONFIGURADA"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def _client():
    kwargs: dict = {"region_name": settings.aws_region}
    explicit = bool(settings.aws_access_key_id and settings.aws_secret_access_key)
    if explicit:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if settings.aws_session_token:
            kwargs["aws_session_token"] = settings.aws_session_token
    logger.info(
        "[SES] Creando cliente AWS SES | region=%s explicit_credentials=%s access_key=%s session_token=%s",
        settings.aws_region,
        explicit,
        _mask_access_key(settings.aws_access_key_id),
        bool(settings.aws_session_token),
    )
    return boto3.client("ses", **kwargs)


async def send_email(*, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> bool:
    """SES directo dentro del request. SES_FROM_EMAIL vacío deshabilita correo en local."""
    logger.info(
        "[SES] Solicitud de envío | from=%s to=%s subject=%r region=%s",
        settings.ses_from_email or "NO_CONFIGURADO",
        to_email,
        subject,
        settings.aws_region,
    )
    if not settings.ses_from_email:
        logger.warning("[SES] Envío omitido porque SES_FROM_EMAIL está vacío | to=%s", to_email)
        return False

    body = {"Text": {"Data": text_body, "Charset": "UTF-8"}}
    if html_body:
        body["Html"] = {"Data": html_body, "Charset": "UTF-8"}

    def _send():
        client = _client()
        logger.info("[SES] Ejecutando send_email en AWS | from=%s to=%s", settings.ses_from_email, to_email)
        return client.send_email(
            Source=settings.ses_from_email,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": body,
            },
        )

    try:
        response = await asyncio.to_thread(_send)
        metadata = response.get("ResponseMetadata", {})
        logger.info(
            "[SES] Correo aceptado por AWS | message_id=%s request_id=%s http_status=%s from=%s to=%s",
            response.get("MessageId"),
            metadata.get("RequestId"),
            metadata.get("HTTPStatusCode"),
            settings.ses_from_email,
            to_email,
        )
        return True
    except ClientError as exc:
        response = exc.response or {}
        error = response.get("Error", {})
        metadata = response.get("ResponseMetadata", {})
        code = error.get("Code", "UNKNOWN")
        message = error.get("Message", str(exc))
        logger.exception(
            "[SES] AWS rechazó el correo | code=%s message=%s request_id=%s http_status=%s region=%s from=%s to=%s access_key=%s",
            code,
            message,
            metadata.get("RequestId"),
            metadata.get("HTTPStatusCode"),
            settings.aws_region,
            settings.ses_from_email,
            to_email,
            _mask_access_key(settings.aws_access_key_id),
        )
        raise AppError("EMAIL_DELIVERY_FAILED", f"No fue posible enviar el correo. AWS SES: {code}", 502) from exc
    except BotoCoreError as exc:
        logger.exception(
            "[SES] Error de Boto/AWS SDK | error_type=%s error=%s region=%s from=%s to=%s",
            type(exc).__name__,
            str(exc),
            settings.aws_region,
            settings.ses_from_email,
            to_email,
        )
        raise AppError("EMAIL_DELIVERY_FAILED", "No fue posible conectar correctamente con Amazon SES", 502) from exc


async def send_issue_assignment_email(*, to_email: str, display_name: str, issue_key: str, issue_title: str,
                                      roles: list[str]) -> bool:
    role_text = " y ".join(roles)
    url = f"{settings.frontend_url.rstrip('/')}/issues/{issue_key}"
    subject = f"{issue_key}: nueva asignación"
    logger.info("[SES][ISSUE] Preparando correo | issue=%s to=%s roles=%s", issue_key, to_email, roles)
    text = (
        f"Hola {display_name},\n\n"
        f"Se te asignó el rol de {role_text} en el ticket {issue_key}: {issue_title}.\n"
        f"Abrir ticket: {url}\n"
    )
    html = (
        f"<p>Hola {escape(display_name)},</p>"
        f"<p>Se te asignó el rol de <strong>{escape(role_text)}</strong> en "
        f"<strong>{escape(issue_key)}</strong>: {escape(issue_title)}.</p>"
        f'<p><a href="{escape(url)}">Abrir ticket</a></p>'
    )
    return await send_email(to_email=to_email, subject=subject, text_body=text, html_body=html)


async def send_project_membership_email(*, to_email: str, display_name: str, project_key: str,
                                        project_name: str, role_name: str, changed: bool = False) -> bool:
    url = f"{settings.frontend_url.rstrip('/')}/projects/{project_key}"
    action = "Se actualizó tu rol" if changed else "Fuiste agregado"
    subject = f"{project_key}: {'rol actualizado' if changed else 'nuevo proyecto'}"
    logger.info(
        "[SES][PROJECT] Preparando correo | project=%s to=%s role=%s changed=%s",
        project_key,
        to_email,
        role_name,
        changed,
    )
    text = (
        f"Hola {display_name},\n\n"
        f"{action} en el proyecto {project_key} - {project_name}.\n"
        f"Rol: {role_name}.\n"
        f"Abrir proyecto: {url}\n"
    )
    html = (
        f"<p>Hola {escape(display_name)},</p>"
        f"<p>{escape(action)} en <strong>{escape(project_key)} - {escape(project_name)}</strong>.</p>"
        f"<p>Rol: <strong>{escape(role_name)}</strong></p>"
        f'<p><a href="{escape(url)}">Abrir proyecto</a></p>'
    )
    return await send_email(to_email=to_email, subject=subject, text_body=text, html_body=html)
