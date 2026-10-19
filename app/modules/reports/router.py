from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.deps import get_current_user
from app.modules.reports.service import (
    activity_report,
    activity_report_html,
    project_summary_html,
    project_summary_report,
)

router = APIRouter(tags=["Reports"])


@router.get("/projects/{project_id}/reports/activity")
async def member_activity_report(
    project_id: UUID,
    period: Literal["day", "week"] = "day",
    report_date: date | None = Query(default=None, alias="date"),
    user_id: UUID | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    return await activity_report(
        session,
        user,
        project_id,
        period=period,
        reference_date=report_date,
        target_user_id=user_id,
    )


@router.get("/projects/{project_id}/reports/activity.html", response_class=HTMLResponse)
async def member_activity_report_download(
    project_id: UUID,
    period: Literal["day", "week"] = "day",
    report_date: date | None = Query(default=None, alias="date"),
    user_id: UUID | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    payload = await activity_report(
        session,
        user,
        project_id,
        period=period,
        reference_date=report_date,
        target_user_id=user_id,
    )
    data = payload["data"]
    filename = f"actividad_{data['project']['key']}_{data['member']['id'][:8]}_{data['window']['start_date']}.html"
    return HTMLResponse(
        activity_report_html(payload),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/projects/{project_id}/reports/summary")
async def project_activity_summary(
    project_id: UUID,
    period: Literal["day", "week"] = "day",
    report_date: date | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    return await project_summary_report(
        session,
        user,
        project_id,
        period=period,
        reference_date=report_date,
    )


@router.get("/projects/{project_id}/reports/summary.html", response_class=HTMLResponse)
async def project_activity_summary_download(
    project_id: UUID,
    period: Literal["day", "week"] = "day",
    report_date: date | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    payload = await project_summary_report(
        session,
        user,
        project_id,
        period=period,
        reference_date=report_date,
    )
    data = payload["data"]
    filename = f"resumen_{data['project']['key']}_{data['window']['start_date']}.html"
    return HTMLResponse(
        project_summary_html(payload),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
