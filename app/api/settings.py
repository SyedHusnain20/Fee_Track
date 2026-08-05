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
non-sensitive student counts), plus links out to Rollover, Category Fees,
and Admin Requests, all of which used to have their own top-nav entries
(or in Admin Requests' case, live in admin_accounts.py) and now live only
here. Their routes/logic are unchanged — this page just adds a front door
to them.

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
from app.services.holidays import list_recent_holidays, mark_holiday

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


def _holiday_rows(session: Session) -> list[dict]:
    """list_recent_holidays() rows enriched with the marking admin's name.
    Holiday has no ORM Relationship() to AdminUser (see the model's
    docstring), so marked_by_id is resolved here rather than in the
    template — one query for however many distinct admins appear in the
    recent-holidays window, not one query per row."""
    holidays = list_recent_holidays(session)
    admin_ids = {h.marked_by_id for h in holidays if h.marked_by_id is not None}
    names = {}
    if admin_ids:
        names = {
            a.id: a.name
            for a in session.exec(select(AdminUser).where(AdminUser.id.in_(admin_ids))).all()
        }
    return [
        {
            "holiday_date": h.holiday_date,
            "marked_by_name": names.get(h.marked_by_id, "—"),
        }
        for h in holidays
    ]


def _pending_admin_count(session: Session) -> int:
    return len(
        session.exec(
            select(AdminUser).where(AdminUser.is_approved == False)  # noqa: E712
        ).all()
    )


def _base_context(
    request: Request,
    session: Session,
    admin: AdminUser,
    *,
    period: Optional[str] = None,
    error: Optional[str] = None,
    due_day: Optional[int] = None,
    due_day_error: Optional[str] = None,
    holiday_error: Optional[str] = None,
) -> dict:
    """Shared template context for every settings/list.html render — GET
    and every POST's re-render-with-error path all show the same page, so
    this keeps the five different handlers below from silently drifting
    out of sync on which keys the template expects (rows, holidays, the
    three independent error slots, etc.)."""
    return {
        "request": request,
        "admin": admin,
        "rows": _rows(session),
        "due_day": due_day if due_day is not None else get_fee_due_day(session),
        "error": error,
        "due_day_error": due_day_error,
        "holidays": _holiday_rows(session),
        "holiday_error": holiday_error,
        "pending_admin_count": _pending_admin_count(session),
        **_financial_totals(session, period or _current_period()),
    }


@router.get("", response_class=HTMLResponse)
async def list_settings(
    request: Request,
    period: Optional[str] = None,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(require_super_admin),
):
    return templates.TemplateResponse(
        "settings/list.html",
        _base_context(request, session, admin, period=period),
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
            _base_context(
                request,
                session,
                admin,
                due_day=due_day,
                due_day_error="Enter a due day between 1 and 31.",
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    set_fee_due_day(session, due_day)
    session.commit()
    return RedirectResponse(url="/settings", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/holidays/today")
async def mark_today_holiday(
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(require_super_admin),
):
    # /holidays/today is two path segments, so it can't collide with
    # POST /{attendance_session} below regardless of registration order
    # (unlike /fee-due-day, that route only ever matches a single segment).
    #
    # Today-only, no reason field: the confirm popup in settings/list.html
    # is the entire input surface for this — one click, one day, per the
    # product decision to keep this a single-purpose "close school today"
    # button rather than a general-purpose date-picker form.
    try:
        mark_holiday(session, school_today(), None, marked_by_id=admin.id)
    except ValueError as exc:
        session.rollback()
        return templates.TemplateResponse(
            "settings/list.html",
            _base_context(request, session, admin, holiday_error=str(exc)),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

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
            _base_context(request, session, admin, error="Enter start time as HH:MM."),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if attendance_session == AttendanceSession.SCHOOL:
        if grace_minutes is None or grace_minutes < 0:
            return templates.TemplateResponse(
                "settings/list.html",
                _base_context(
                    request, session, admin, error="Grace period can't be negative."
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        set_session_timing(session, attendance_session, parsed_start, grace_minutes)
    else:
        # Academy: start time only — grace_minutes ignored even if submitted.
        set_session_timing(session, attendance_session, parsed_start, grace_minutes=None)

    session.commit()
    return RedirectResponse(url="/settings", status_code=status.HTTP_303_SEE_OTHER)