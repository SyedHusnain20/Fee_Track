"""Attendance timing settings — Section 3: admin capability to "set
category timings + grace periods", updated for the School/Academy kiosk
redesign. School gets a start time + grace period (drives late
calculation); Academy gets a start time only, for reference/reporting —
there's no late judgment for Academy scans at all.
"""
from datetime import time
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.api.deps import get_current_admin
from app.core.database import get_session
from app.models.admin_user import AdminUser
from app.models.enums import AttendanceSession
from app.services.attendance_settings import (
    get_session_grace_minutes,
    get_session_start_time,
    set_session_timing,
)

router = APIRouter(prefix="/settings", tags=["settings"])
templates = Jinja2Templates(directory="app/templates")

SESSION_LABELS = {
    AttendanceSession.SCHOOL: "School",
    AttendanceSession.ACADEMY: "Academy",
}


def _rows(session: Session) -> list[dict]:
    return [
        {
            "session": s,
            "label": SESSION_LABELS[s],
            "start_time": get_session_start_time(session, s),
            "grace_minutes": get_session_grace_minutes(session, s) if s == AttendanceSession.SCHOOL else None,
            "has_grace": s == AttendanceSession.SCHOOL,
        }
        for s in AttendanceSession
    ]


@router.get("", response_class=HTMLResponse)
async def list_settings(
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    return templates.TemplateResponse(
        "settings/list.html",
        {"request": request, "admin": admin, "rows": _rows(session), "error": None},
    )


@router.post("/{attendance_session}")
async def update_setting(
    attendance_session: AttendanceSession,
    request: Request,
    start_time: str = Form(...),
    grace_minutes: Optional[int] = Form(None),
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    try:
        hour_str, minute_str = start_time.split(":")
        parsed_start = time(int(hour_str), int(minute_str))
    except (ValueError, IndexError):
        return templates.TemplateResponse(
            "settings/list.html",
            {
                "request": request, "admin": admin, "rows": _rows(session),
                "error": "Enter start time as HH:MM.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if attendance_session == AttendanceSession.SCHOOL:
        if grace_minutes is None or grace_minutes < 0:
            return templates.TemplateResponse(
                "settings/list.html",
                {
                    "request": request, "admin": admin, "rows": _rows(session),
                    "error": "Grace period can't be negative.",
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        set_session_timing(session, attendance_session, parsed_start, grace_minutes)
    else:
        # Academy: start time only — grace_minutes ignored even if submitted.
        set_session_timing(session, attendance_session, parsed_start, grace_minutes=None)

    session.commit()
    return RedirectResponse(url="/settings", status_code=status.HTTP_303_SEE_OTHER)