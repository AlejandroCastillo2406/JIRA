from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.permissions import Permission, can_manage_project, ensure_project_permission
from app.modules.audit.models import AuditEvent
from app.modules.issues.models import Issue, IssueBlock
from app.modules.projects.models import Project, ProjectMember
from app.modules.users.models import User
from app.modules.workflows.models import WorkflowStatus


ACTION_LABELS = {
    "ISSUE_CREATED": "Creó el ticket",
    "ISSUE_UPDATED": "Actualizó el ticket",
    "STATUS_CHANGED": "Cambió el estado",
    "COMMENT_CREATED": "Agregó un comentario",
    "IMAGE_ADDED": "Agregó una imagen",
    "IMAGE_REMOVED": "Eliminó una imagen",
    "ISSUE_BLOCKED": "Bloqueó el ticket",
    "ISSUE_UNBLOCKED": "Desbloqueó el ticket",
    "RANK_CHANGED": "Reordenó el ticket",
    "ISSUE_DELETED": "Eliminó el ticket",
    "PROJECT_CREATED": "Creó el proyecto",
    "PROJECT_DELETED": "Eliminó el proyecto",
}

FIELD_LABELS = {
    "title": "título",
    "description": "descripción",
    "priority_id": "prioridad",
    "assignee_id": "responsable",
    "reviewer_id": "revisor",
    "story_points": "puntos",
    "due_date": "fecha límite",
    "rank": "orden",
}


def _tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def report_window(reference_date: date, period: str, timezone_name: str | None) -> dict:
    tz = _tz(timezone_name)
    if period == "week":
        start_date = reference_date - timedelta(days=reference_date.weekday())
        end_date = start_date + timedelta(days=7)
        label = f"Semana del {start_date.strftime('%d/%m/%Y')} al {(end_date - timedelta(days=1)).strftime('%d/%m/%Y')}"
    else:
        start_date = reference_date
        end_date = reference_date + timedelta(days=1)
        label = reference_date.strftime("%d/%m/%Y")
    start_local = datetime.combine(start_date, time.min, tzinfo=tz)
    end_local = datetime.combine(end_date, time.min, tzinfo=tz)
    return {
        "period": period,
        "reference_date": reference_date.isoformat(),
        "start_date": start_date.isoformat(),
        "end_date_exclusive": end_date.isoformat(),
        "start_utc": start_local.astimezone(timezone.utc),
        "end_utc": end_local.astimezone(timezone.utc),
        "timezone": getattr(tz, "key", "UTC"),
        "label": label,
    }


def _today_for(timezone_name: str | None) -> date:
    return datetime.now(_tz(timezone_name)).date()


def _event_metric_defaults() -> dict[str, int]:
    return {
        "actions": 0,
        "tickets_touched": 0,
        "tickets_created": 0,
        "status_changes": 0,
        "moved_to_done": 0,
        "comments": 0,
        "updates": 0,
        "images_added": 0,
        "blocks": 0,
        "unblocks": 0,
        "deleted": 0,
    }


def _status_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except (ValueError, TypeError):
        return None


def _metrics_from_events(events: list[AuditEvent], status_categories: dict[UUID, str]) -> dict[str, int]:
    metrics = _event_metric_defaults()
    touched: set[UUID] = set()
    for event in events:
        metrics["actions"] += 1
        if event.entity_type == "issue":
            touched.add(event.entity_id)
        if event.action == "ISSUE_CREATED":
            metrics["tickets_created"] += 1
        elif event.action == "STATUS_CHANGED":
            metrics["status_changes"] += 1
            target = _status_uuid(event.new_value)
            if target and status_categories.get(target) == "DONE":
                metrics["moved_to_done"] += 1
        elif event.action == "COMMENT_CREATED":
            metrics["comments"] += 1
        elif event.action == "ISSUE_UPDATED":
            metrics["updates"] += 1
        elif event.action == "IMAGE_ADDED":
            metrics["images_added"] += 1
        elif event.action == "ISSUE_BLOCKED":
            metrics["blocks"] += 1
        elif event.action == "ISSUE_UNBLOCKED":
            metrics["unblocks"] += 1
        elif event.action == "ISSUE_DELETED":
            metrics["deleted"] += 1
    metrics["tickets_touched"] = len(touched)
    return metrics


def _event_detail(event: AuditEvent) -> str | None:
    metadata = event.metadata_json or {}
    if event.action == "STATUS_CHANGED":
        old = metadata.get("old")
        new = metadata.get("new")
        if old and new:
            return f"{old} → {new}"
    if event.action == "ISSUE_UPDATED" and event.field_name:
        return FIELD_LABELS.get(event.field_name, event.field_name)
    if event.action == "ISSUE_BLOCKED" and event.new_value:
        return event.new_value[:180]
    if event.action in {"IMAGE_ADDED", "IMAGE_REMOVED"} and metadata.get("filename"):
        return str(metadata["filename"])
    return None


def _serialize_event(event: AuditEvent, issue_map: dict[UUID, Issue], actor_map: dict[UUID, User], tz: ZoneInfo) -> dict:
    issue = issue_map.get(event.entity_id) if event.entity_type == "issue" else None
    actor = actor_map.get(event.actor_user_id)
    created = event.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    local_created = created.astimezone(tz)
    return {
        "id": str(event.id),
        "action": event.action,
        "label": ACTION_LABELS.get(event.action, event.action.replace("_", " ").title()),
        "detail": _event_detail(event),
        "actor": {
            "id": str(actor.id) if actor else str(event.actor_user_id),
            "display_name": actor.display_name if actor else "Usuario",
            "email": actor.email if actor else None,
        },
        "issue": ({
            "id": str(issue.id),
            "issue_key": issue.issue_key,
            "title": issue.title,
        } if issue else None),
        "created_at": event.created_at.isoformat(),
        "created_at_local": local_created.isoformat(),
        "created_label": local_created.strftime("%d/%m/%Y %H:%M"),
    }


async def _project(session: AsyncSession, project_id: UUID) -> Project:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.status == "ACTIVE"))
    if not project:
        raise AppError("NOT_FOUND", "Proyecto no encontrado", 404)
    return project


async def _statuses(session: AsyncSession, project: Project) -> tuple[dict[UUID, WorkflowStatus], dict[UUID, str]]:
    rows = list((await session.scalars(
        select(WorkflowStatus).where(WorkflowStatus.workflow_id == project.default_workflow_id)
    )).all())
    by_id = {row.id: row for row in rows}
    return by_id, {row.id: row.category for row in rows}


async def _events(
    session: AsyncSession,
    project_id: UUID,
    start_utc: datetime,
    end_utc: datetime,
    actor_user_id: UUID | None = None,
    limit: int = 1000,
) -> tuple[list[AuditEvent], int]:
    filters = [
        AuditEvent.project_id == project_id,
        AuditEvent.created_at >= start_utc,
        AuditEvent.created_at < end_utc,
    ]
    if actor_user_id:
        filters.append(AuditEvent.actor_user_id == actor_user_id)
    total = await session.scalar(select(func.count(AuditEvent.id)).where(*filters)) or 0
    rows = list((await session.scalars(
        select(AuditEvent).where(*filters).order_by(AuditEvent.created_at.desc()).limit(limit)
    )).all())
    return rows, total


async def _issue_map(session: AsyncSession, events: list[AuditEvent]) -> dict[UUID, Issue]:
    ids = list({event.entity_id for event in events if event.entity_type == "issue"})
    if not ids:
        return {}
    rows = list((await session.scalars(select(Issue).where(Issue.id.in_(ids)))).unique().all())
    return {row.id: row for row in rows}


async def _actor_map(session: AsyncSession, actor_ids: set[UUID]) -> dict[UUID, User]:
    if not actor_ids:
        return {}
    rows = list((await session.scalars(select(User).where(User.id.in_(actor_ids)))).unique().all())
    return {row.id: row for row in rows}


async def _project_issue_snapshot(session: AsyncSession, project_id: UUID) -> list[dict]:
    rows = (await session.execute(
        select(
            Issue.id,
            Issue.assignee_id,
            Issue.reviewer_id,
            Issue.status_id,
            Issue.due_date,
            Issue.started_at,
            Issue.completed_at,
        ).where(Issue.project_id == project_id, Issue.deleted_at.is_(None))
    )).all()
    return [
        {
            "id": row.id,
            "assignee_id": row.assignee_id,
            "reviewer_id": row.reviewer_id,
            "status_id": row.status_id,
            "due_date": row.due_date,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
        }
        for row in rows
    ]


async def _open_block_ids(session: AsyncSession, project_id: UUID) -> set[UUID]:
    rows = (await session.execute(
        select(IssueBlock.issue_id)
        .join(Issue, Issue.id == IssueBlock.issue_id)
        .where(Issue.project_id == project_id, Issue.deleted_at.is_(None), IssueBlock.unblocked_at.is_(None))
    )).all()
    return {row.issue_id for row in rows}


def _current_metrics_for_user(
    user_id: UUID,
    issue_rows: list[dict],
    status_categories: dict[UUID, str],
    open_block_ids: set[UUID],
    today: date,
    start_utc: datetime,
    end_utc: datetime,
) -> dict[str, int]:
    metrics = {
        "assigned_total": 0,
        "assigned_open": 0,
        "reviewing_open": 0,
        "in_progress": 0,
        "overdue": 0,
        "blocked": 0,
        "completed_in_period": 0,
        "started_in_period": 0,
    }
    for row in issue_rows:
        category = status_categories.get(row["status_id"], "TODO")
        is_assignee = row["assignee_id"] == user_id
        is_reviewer = row["reviewer_id"] == user_id
        if is_assignee:
            metrics["assigned_total"] += 1
            if category != "DONE":
                metrics["assigned_open"] += 1
            if category == "IN_PROGRESS":
                metrics["in_progress"] += 1
            if row["due_date"] and row["due_date"] < today and category != "DONE":
                metrics["overdue"] += 1
            if row["id"] in open_block_ids:
                metrics["blocked"] += 1
            if row["completed_at"]:
                completed = row["completed_at"]
                if completed.tzinfo is None:
                    completed = completed.replace(tzinfo=timezone.utc)
                if start_utc <= completed < end_utc:
                    metrics["completed_in_period"] += 1
            if row["started_at"]:
                started = row["started_at"]
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                if start_utc <= started < end_utc:
                    metrics["started_in_period"] += 1
        if is_reviewer and category != "DONE":
            metrics["reviewing_open"] += 1
    return metrics


async def _resolve_target(session: AsyncSession, user, project_id: UUID, target_user_id: UUID | None) -> tuple[User, bool]:
    await ensure_project_permission(session, user, project_id, Permission.PROJECT_READ)
    manager = await can_manage_project(session, user, project_id)
    target_id = target_user_id or user.id
    if target_id != user.id and not manager:
        raise AppError("FORBIDDEN", "Solo administración puede consultar la actividad de otro integrante", 403)
    target = await session.scalar(select(User).where(User.id == target_id))
    if not target:
        raise AppError("NOT_FOUND", "Usuario no encontrado", 404)
    if target_id != user.id:
        member = await session.scalar(select(ProjectMember.user_id).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == target_id
        ))
        if not member:
            raise AppError("NOT_FOUND", "El usuario no pertenece al proyecto", 404)
    return target, manager


async def activity_report(
    session: AsyncSession,
    user,
    project_id: UUID,
    *,
    period: str,
    reference_date: date | None,
    target_user_id: UUID | None,
) -> dict:
    target, manager = await _resolve_target(session, user, project_id, target_user_id)
    project = await _project(session, project_id)
    ref = reference_date or _today_for(target.timezone)
    window = report_window(ref, period, target.timezone)
    status_map, status_categories = await _statuses(session, project)
    events, total_events = await _events(
        session, project_id, window["start_utc"], window["end_utc"], actor_user_id=target.id
    )
    issue_map = await _issue_map(session, events)
    actors = await _actor_map(session, {target.id})
    tz = _tz(target.timezone)
    timeline = [_serialize_event(event, issue_map, actors, tz) for event in events]
    issue_rows = await _project_issue_snapshot(session, project_id)
    blocked_ids = await _open_block_ids(session, project_id)
    today = _today_for(target.timezone)
    current = _current_metrics_for_user(
        target.id, issue_rows, status_categories, blocked_ids, today, window["start_utc"], window["end_utc"]
    )
    activity = _metrics_from_events(events, status_categories)

    notes: list[str] = []
    if activity["actions"] == 0:
        notes.append("No se registraron acciones del integrante durante el periodo seleccionado.")
    else:
        notes.append(
            f"Se registraron {activity['actions']} acciones sobre {activity['tickets_touched']} ticket(s)."
        )
        if activity["moved_to_done"]:
            notes.append(f"El integrante movió {activity['moved_to_done']} ticket(s) a un estado terminado.")
        if activity["comments"]:
            notes.append(f"Agregó {activity['comments']} comentario(s) durante el periodo.")
        if activity["blocks"]:
            notes.append(f"Registró {activity['blocks']} bloqueo(s) que conviene revisar en contexto.")
    if current["overdue"]:
        notes.append(f"Actualmente tiene {current['overdue']} ticket(s) asignado(s) vencido(s).")
    if current["blocked"]:
        notes.append(f"Actualmente tiene {current['blocked']} ticket(s) asignado(s) bloqueado(s).")

    return {
        "data": {
            "report_type": "member_activity",
            "project": {"id": str(project.id), "key": project.key, "name": project.name},
            "member": {
                "id": str(target.id),
                "display_name": target.display_name,
                "email": target.email,
                "timezone": target.timezone,
            },
            "window": {k: v for k, v in window.items() if k not in {"start_utc", "end_utc"}},
            "activity": activity,
            "current_workload": current,
            "summary": notes,
            "timeline": timeline,
            "timeline_total": total_events,
            "timeline_truncated": total_events > len(timeline),
            "viewer_can_manage_project": manager,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    }


def _member_snapshot(
    member: User,
    events: list[AuditEvent],
    issue_rows: list[dict],
    status_categories: dict[UUID, str],
    blocked_ids: set[UUID],
    today: date,
    start_utc: datetime,
    end_utc: datetime,
    role: str,
) -> dict:
    return {
        "user_id": str(member.id),
        "display_name": member.display_name,
        "email": member.email,
        "role": role,
        "activity": _metrics_from_events(events, status_categories),
        "current_workload": _current_metrics_for_user(
            member.id, issue_rows, status_categories, blocked_ids, today, start_utc, end_utc
        ),
    }


async def project_summary_report(
    session: AsyncSession,
    user,
    project_id: UUID,
    *,
    period: str,
    reference_date: date | None,
) -> dict:
    await ensure_project_permission(session, user, project_id, Permission.PROJECT_READ)
    if not await can_manage_project(session, user, project_id):
        raise AppError("FORBIDDEN", "Solo administración puede consultar el resumen global del proyecto", 403)

    project = await _project(session, project_id)
    ref = reference_date or _today_for(user.timezone)
    window = report_window(ref, period, user.timezone)
    status_map, status_categories = await _statuses(session, project)
    events, total_events = await _events(session, project_id, window["start_utc"], window["end_utc"])
    issue_map = await _issue_map(session, events)
    issue_rows = await _project_issue_snapshot(session, project_id)
    blocked_ids = await _open_block_ids(session, project_id)
    today = _today_for(user.timezone)

    memberships = list((await session.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project_id)
    )).all())
    membership_by_user = {row.user_id: row for row in memberships}

    actor_ids = {event.actor_user_id for event in events}
    all_user_ids = actor_ids | set(membership_by_user)
    actor_map = await _actor_map(session, all_user_ids)
    tz = _tz(user.timezone)
    timeline = [_serialize_event(event, issue_map, actor_map, tz) for event in events]

    events_by_actor: dict[UUID, list[AuditEvent]] = defaultdict(list)
    for event in events:
        events_by_actor[event.actor_user_id].append(event)

    member_rows: list[dict] = []
    # La tabla "por integrante" contiene miembros reales del proyecto.
    # Los administradores globales que actúen sin ser miembros sí aparecen en la línea de tiempo,
    # pero no se mezclan con las métricas del equipo.
    member_user_ids = sorted(
        membership_by_user,
        key=lambda uid: (actor_map.get(uid).display_name if actor_map.get(uid) else ""),
    )
    for user_id in member_user_ids:
        member = actor_map.get(user_id)
        membership = membership_by_user.get(user_id)
        if not member or not membership:
            continue
        member_rows.append(_member_snapshot(
            member,
            events_by_actor.get(user_id, []),
            issue_rows,
            status_categories,
            blocked_ids,
            today,
            window["start_utc"],
            window["end_utc"],
            membership.role.code,
        ))

    category_counts = {"TODO": 0, "IN_PROGRESS": 0, "DONE": 0}
    unassigned = 0
    overdue = 0
    completed_in_period = 0
    started_in_period = 0
    for row in issue_rows:
        category = status_categories.get(row["status_id"], "TODO")
        category_counts[category] = category_counts.get(category, 0) + 1
        if row["assignee_id"] is None and category != "DONE":
            unassigned += 1
        if row["due_date"] and row["due_date"] < today and category != "DONE":
            overdue += 1
        if row["completed_at"]:
            completed = row["completed_at"]
            if completed.tzinfo is None:
                completed = completed.replace(tzinfo=timezone.utc)
            if window["start_utc"] <= completed < window["end_utc"]:
                completed_in_period += 1
        if row["started_at"]:
            started = row["started_at"]
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if window["start_utc"] <= started < window["end_utc"]:
                started_in_period += 1

    event_metrics = _metrics_from_events(events, status_categories)
    current = {
        "total": len(issue_rows),
        "todo": category_counts.get("TODO", 0),
        "in_progress": category_counts.get("IN_PROGRESS", 0),
        "done": category_counts.get("DONE", 0),
        "unassigned": unassigned,
        "overdue": overdue,
        "blocked": len(blocked_ids),
    }
    period_metrics = {
        **event_metrics,
        "completed_tickets": completed_in_period,
        "started_tickets": started_in_period,
        "active_members": sum(1 for row in member_rows if row["activity"]["actions"] > 0),
    }

    highlights: list[str] = []
    if total_events == 0:
        highlights.append("No se registró actividad en el proyecto durante el periodo seleccionado.")
    else:
        highlights.append(
            f"Se registraron {total_events} acciones y participaron {period_metrics['active_members']} integrante(s)."
        )
        highlights.append(
            f"Durante el periodo se iniciaron {started_in_period} ticket(s) y se completaron {completed_in_period}."
        )
        created = event_metrics["tickets_created"]
        if created > completed_in_period:
            highlights.append(
                f"Se crearon {created} ticket(s), por encima de los {completed_in_period} completados en el mismo periodo."
            )
        elif completed_in_period > created:
            highlights.append(
                f"Se completaron más tickets ({completed_in_period}) de los que se crearon ({created}) durante el periodo."
            )
    if current["blocked"]:
        highlights.append(f"Hay {current['blocked']} ticket(s) actualmente bloqueado(s).")
    if current["overdue"]:
        highlights.append(f"Hay {current['overdue']} ticket(s) vencido(s) que siguen abiertos.")
    if current["unassigned"]:
        highlights.append(f"Hay {current['unassigned']} ticket(s) abiertos sin responsable asignado.")
    if not any((current["blocked"], current["overdue"], current["unassigned"])):
        highlights.append("No hay tickets abiertos bloqueados, vencidos ni sin responsable en este momento.")

    return {
        "data": {
            "report_type": "project_summary",
            "project": {"id": str(project.id), "key": project.key, "name": project.name},
            "window": {k: v for k, v in window.items() if k not in {"start_utc", "end_utc"}},
            "current": current,
            "period": period_metrics,
            "highlights": highlights,
            "members": member_rows,
            "timeline": timeline,
            "timeline_total": total_events,
            "timeline_truncated": total_events > len(timeline),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "calculation": "deterministic",
        }
    }


def _html_document(title: str, subtitle: str, body: str) -> str:
    return f"""<!doctype html>
<html lang=\"es\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>{escape(title)}</title>
<style>
:root{{--ink:#172033;--muted:#64748b;--line:#e2e8f0;--soft:#f8fafc;--brand:#2563eb;}}
*{{box-sizing:border-box}} body{{margin:0;background:#f1f5f9;color:var(--ink);font:14px/1.5 Arial,sans-serif}}
.wrap{{max-width:1100px;margin:32px auto;background:#fff;border:1px solid var(--line);border-radius:18px;overflow:hidden}}
.header{{padding:30px 34px;background:#0f172a;color:#fff}} h1{{margin:0 0 5px;font-size:28px}} .sub{{color:#cbd5e1}}
.content{{padding:30px 34px}} .grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0 26px}}
.card{{border:1px solid var(--line);border-radius:12px;padding:14px;background:#fff}} .metric{{font-size:24px;font-weight:800;margin-top:5px}}
.muted{{color:var(--muted)}} h2{{font-size:18px;margin:28px 0 10px}} ul{{padding-left:20px}} li{{margin:5px 0}}
table{{width:100%;border-collapse:collapse;margin-top:10px}} th,td{{padding:10px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}} th{{font-size:12px;text-transform:uppercase;color:var(--muted);background:var(--soft)}}
.badge{{display:inline-block;padding:2px 8px;border-radius:999px;background:#eff6ff;color:#1d4ed8;font-size:12px;font-weight:700}}
.footer{{padding:18px 34px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}}
@media(max-width:760px){{.grid{{grid-template-columns:repeat(2,1fr)}}.wrap{{margin:0;border-radius:0}}.content,.header{{padding:22px}}}}
@media print{{body{{background:#fff}}.wrap{{margin:0;max-width:none;border:0}}}}
</style>
</head><body><main class=\"wrap\"><header class=\"header\"><h1>{escape(title)}</h1><div class=\"sub\">{escape(subtitle)}</div></header><section class=\"content\">{body}</section><footer class=\"footer\">Reporte calculado con datos de ProjectFlow. No utiliza IA.</footer></main></body></html>"""


def activity_report_html(payload: dict) -> str:
    data = payload["data"]
    activity = data["activity"]
    workload = data["current_workload"]
    cards = [
        ("Acciones", activity["actions"]),
        ("Tickets tocados", activity["tickets_touched"]),
        ("Completados asignados", workload["completed_in_period"]),
        ("Abiertos asignados", workload["assigned_open"]),
    ]
    card_html = "".join(f'<div class="card"><div class="muted">{escape(label)}</div><div class="metric">{value}</div></div>' for label, value in cards)
    summary_html = "".join(f"<li>{escape(line)}</li>" for line in data["summary"])
    rows = "".join(
        "<tr>"
        f"<td>{escape(item['created_label'])}</td>"
        f"<td>{escape(item['issue']['issue_key'] if item['issue'] else 'Proyecto')}</td>"
        f"<td>{escape(item['label'])}</td>"
        f"<td>{escape(item['detail'] or '')}</td>"
        "</tr>"
        for item in data["timeline"]
    ) or '<tr><td colspan="4" class="muted">Sin actividad en este periodo.</td></tr>'
    body = f"""
<div><span class=\"badge\">{escape(data['window']['label'])}</span></div>
<h2>{escape(data['member']['display_name'])}</h2><div class=\"muted\">{escape(data['member']['email'])}</div>
<div class=\"grid\">{card_html}</div>
<h2>Resumen calculado</h2><ul>{summary_html}</ul>
<h2>Actividad registrada</h2><table><thead><tr><th>Fecha</th><th>Ticket</th><th>Acción</th><th>Detalle</th></tr></thead><tbody>{rows}</tbody></table>
"""
    title = f"Actividad · {data['project']['key']} · {data['member']['display_name']}"
    return _html_document(title, data["window"]["label"], body)


def project_summary_html(payload: dict) -> str:
    data = payload["data"]
    current = data["current"]
    period = data["period"]
    cards = [
        ("Tickets actuales", current["total"]),
        ("En progreso", current["in_progress"]),
        ("Completados periodo", period["completed_tickets"]),
        ("Acciones periodo", period["actions"]),
        ("Bloqueados", current["blocked"]),
        ("Vencidos", current["overdue"]),
        ("Sin responsable", current["unassigned"]),
        ("Integrantes activos", period["active_members"]),
    ]
    card_html = "".join(f'<div class="card"><div class="muted">{escape(label)}</div><div class="metric">{value}</div></div>' for label, value in cards)
    highlights = "".join(f"<li>{escape(line)}</li>" for line in data["highlights"])
    member_rows = "".join(
        "<tr>"
        f"<td>{escape(row['display_name'])}<div class=\"muted\">{escape(row['email'])}</div></td>"
        f"<td>{escape(row['role'])}</td>"
        f"<td>{row['activity']['actions']}</td>"
        f"<td>{row['activity']['tickets_touched']}</td>"
        f"<td>{row['current_workload']['assigned_open']}</td>"
        f"<td>{row['current_workload']['overdue']}</td>"
        "</tr>"
        for row in data["members"]
    ) or '<tr><td colspan="6" class="muted">Sin integrantes para mostrar.</td></tr>'
    activity_rows = "".join(
        "<tr>"
        f"<td>{escape(item['created_label'])}</td>"
        f"<td>{escape(item['actor']['display_name'])}</td>"
        f"<td>{escape(item['issue']['issue_key'] if item['issue'] else 'Proyecto')}</td>"
        f"<td>{escape(item['label'])}</td>"
        f"<td>{escape(item['detail'] or '')}</td>"
        "</tr>"
        for item in data["timeline"]
    ) or '<tr><td colspan="5" class="muted">Sin actividad en este periodo.</td></tr>'
    body = f"""
<div><span class=\"badge\">{escape(data['window']['label'])}</span></div>
<div class=\"grid\">{card_html}</div>
<h2>Resumen ejecutivo calculado</h2><ul>{highlights}</ul>
<h2>Actividad por integrante</h2><table><thead><tr><th>Integrante</th><th>Rol</th><th>Acciones</th><th>Tickets tocados</th><th>Abiertos asignados</th><th>Vencidos</th></tr></thead><tbody>{member_rows}</tbody></table>
<h2>Todas las actividades del periodo</h2><table><thead><tr><th>Fecha</th><th>Integrante</th><th>Ticket</th><th>Acción</th><th>Detalle</th></tr></thead><tbody>{activity_rows}</tbody></table>
"""
    title = f"Resumen de actividad · {data['project']['key']}"
    return _html_document(title, data["window"]["label"], body)
