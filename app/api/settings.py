"""Attendance timing settings — Section 3: admin capability to "set
category timings + grace periods". Scoped to just that for Step 9;
academic_year_reset_month is seeded (scripts/seed_reference_data.py) but
gets its own edit UI in Step 11, when the year-end archive job actually
reads it — no need to build that control surface before anything consumes it.
"""
from datetime import time

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.api.deps import get_current_admin
from app.core.database import get_session
from app.models.admin_user import AdminUser
from app.models.enums import FeeCategory
from app.services.attendance_settings import (
    get_category_grace_minutes,
    get_category_start_time,
    set_category_timing,
)

router = APIRouter(prefix="/settings", tags=["settings"])
templates = Jinja2Templates(directory="app/templates")

CATEGORY_LABELS = {
    FeeCategory.SCHOOL: "School",
    FeeCategory.COACHING: "Coaching",
    FeeCategory.ENGLISH: "English Language",
    FeeCategory.COMPUTER: "Computer Courses",
}


def _rows(session: Session) -> list[dict]:
    return [
        {
            "category": c,
            "label": CATEGORY_LABELS[c],
            "start_time": get_category_start_time(session, c),
            "grace_minutes": get_category_grace_minutes(session, c),
        }
        for c in FeeCategory
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


@router.post("/{category}")
async def update_setting(
    category: FeeCategory,
    request: Request,
    start_time: str = Form(...),
    grace_minutes: int = Form(...),
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

    if grace_minutes < 0:
        return templates.TemplateResponse(
            "settings/list.html",
            {
                "request": request, "admin": admin, "rows": _rows(session),
                "error": "Grace period can't be negative.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    set_category_timing(session, category, parsed_start, grace_minutes)
    session.commit()
    return RedirectResponse(url="/settings", status_code=status.HTTP_303_SEE_OTHER)
