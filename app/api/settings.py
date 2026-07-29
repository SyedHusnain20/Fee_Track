"""Attendance timing + fee due-day settings — Section 3: admin capability
to "set category timings + grace periods", updated for the School/Academy
kiosk redesign. School gets a start time + grace period (drives late
calculation); Academy gets a start time only, for reference/reporting —
there's no late judgment for Academy scans at all.

Also hosts the fee due-day setting (the day of the month after which an
unpaid student is flagged overdue on /students — see
app.services.fee_settings), a period-scoped Financial Summary (the actual
Rs revenue/collected/outstanding figures — moved here from /fee-cycles,
since those are sensitive financial figures that shouldn't be visible to
every admin who opens that page; /fee-cycles itself now only shows
non-sensitive student counts), plus links out to Rollover and Category
Fees, both of which used to have their own top-nav entries and now live
only here. Their routes/logic are unchanged — this page just adds a front
door to them.

Every route in this module requires require_super_admin (app.api.deps),
not the plain get_current_admin used elsewhere — regular admins can use
the rest of the software but not this page, per explicit access-control
decision. The navbar link to /settings is also hidden from non-super-
admins (app/templates/base.html), but that's cosmetic; this dependency
is the actual enforcement.
"""

from datetime import time
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.api.deps import require_super_admin
from app.core.database import get_session
from app.core.timezone import school_today
from app.models.admin_user import AdminUser
from app.models.enums import AttendanceSession, FeeCycleStatus
from app.models.fee_cycle import FeeCycle
from app.services.attendance_settings import (
    get_session_grace_minutes,
    get_session_start_time,
    set_session_timing,
)
from app.services.fee_settings import get_fee_due_day, set_fee_due_day

router = APIRouter(prefix="/settings", tags=["settings"])
templates = Jinja2Templates(directory="app/templates")

SESSION_LABELS = {
    AttendanceSession.SCHOOL: "School",
    AttendanceSession.ACADEMY: "Academy",
}


def _current_period() -> str:
    today = school_today()
    return f"{today.year:04d}-{today.month:02d}"


def _financial_totals(session: Session, period: str) -> dict:
    cycles = session.exec(select(FeeCycle).where(FeeCycle.period == period)).all()
    total_revenue = sum((c.total_due for c in cycles), Decimal("0.00"))
    total_collected = sum(
        (c.total_due for c in cycles if c.status == FeeCycleStatus.PAID), Decimal("0.00")
    )
    total_outstanding = sum(
        (c.total_due for c in cycles if c.status == FeeCycleStatus.UNPAID), Decimal("0.00")
    )
    return {
        "fin_period": period,
        "total_revenue": total_revenue,
        "total_collected": total_collected,
        "total_outstanding": total_outstanding,
        "fin_cycle_count": len(cycles),
    }


def _rows(session: Session) -> list[dict]:
    return [
        {
            "session": s,
            "label": SESSION_LABELS[s],
            "start_time": get_session_start_time(session, s),
            "grace_minutes": get_session_grace_minutes(session, s)
            if s == AttendanceSession.SCHOOL
            else None,
            "has_grace": s == AttendanceSession.SCHOOL,
        }
        for s in AttendanceSession
    ]


@router.get("", response_class=HTMLResponse)
async def list_settings(
    request: Request,
    period: Optional[str] = None,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(require_super_admin),
):
    period = period or _current_period()
    return templates.TemplateResponse(
        "settings/list.html",
        {
            "request": request,
            "admin": admin,
            "rows": _rows(session),
            "due_day": get_fee_due_day(session),
            "error": None,
            "due_day_error": None,
            **_financial_totals(session, period),
        },
    )


@router.post("/fee-due-day")
async def update_fee_due_day(
    request: Request,
    due_day: int = Form(...),
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(require_super_admin),
):
    # Registered before POST /{attendance_session} below on purpose — that
    # route's path parameter is typed as the AttendanceSession enum, and
    # FastAPI matches routes by path shape first; if this route were
    # declared after it, "/settings/fee-due-day" would match that pattern
    # instead and fail enum validation before ever reaching this handler.
    if due_day < 1 or due_day > 31:
        return templates.TemplateResponse(
            "settings/list.html",
            {
                "request": request,
                "admin": admin,
                "rows": _rows(session),
                "due_day": due_day,
                "error": None,
                "due_day_error": "Enter a due day between 1 and 31.",
                **_financial_totals(session, _current_period()),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    set_fee_due_day(session, due_day)
    session.commit()
    return RedirectResponse(url="/settings", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{attendance_session}")
async def update_setting(
    attendance_session: AttendanceSession,
    request: Request,
    start_time: str = Form(...),
    grace_minutes: Optional[int] = Form(None),
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(require_super_admin),
):
    try:
        hour_str, minute_str = start_time.split(":")
        parsed_start = time(int(hour_str), int(minute_str))
    except (ValueError, IndexError):
        return templates.TemplateResponse(
            "settings/list.html",
            {
                "request": request,
                "admin": admin,
                "rows": _rows(session),
                "due_day": get_fee_due_day(session),
                "error": "Enter start time as HH:MM.",
                "due_day_error": None,
                **_financial_totals(session, _current_period()),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if attendance_session == AttendanceSession.SCHOOL:
        if grace_minutes is None or grace_minutes < 0:
            return templates.TemplateResponse(
                "settings/list.html",
                {
                    "request": request,
                    "admin": admin,
                    "rows": _rows(session),
                    "due_day": get_fee_due_day(session),
                    "error": "Grace period can't be negative.",
                    "due_day_error": None,
                    **_financial_totals(session, _current_period()),
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        set_session_timing(session, attendance_session, parsed_start, grace_minutes)
    else:
        # Academy: start time only — grace_minutes ignored even if submitted.
        set_session_timing(session, attendance_session, parsed_start, grace_minutes=None)

    session.commit()
    return RedirectResponse(url="/settings", status_code=status.HTTP_303_SEE_OTHER)
