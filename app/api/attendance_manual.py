"""Manual attendance entry — the fallback for when the QR scanner itself
is unavailable or malfunctioning. Deliberately the opposite trust model
from /kiosk: that endpoint is unauthenticated by design (see
app.api.kiosk's docstring), this one requires a logged-in admin, since
typing an ID is far easier to get wrong or abuse than scanning a physical
card, and every record it creates needs an accountable author (see
AttendanceRecord.marked_by_id).

Open to any logged-in admin, not just a super admin — this is a day-to-day
operational task in the same tier as the kiosk itself, not an
administrative one like /settings or Admin Requests.

Phase 2 shipped the backend route only (JSON in/out, like /kiosk/scan).
Phase 3 adds GET (the actual page) alongside it — an ordinary
Jinja2/base.html admin page, not the kiosk's standalone dark-theme
template, since this lives in the regular admin nav and is used by a
logged-in person at a desk/counter rather than an unattended gate device.
Unlike /kiosk/scan, POST here goes through the app-wide CSRF check
(app.core.csrf skips /kiosk specifically, and only /kiosk), so the page's
JS submits the session's csrf_token as a normal form field alongside
identifier/session.
"""

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.api.deps import get_current_admin
from app.core.database import get_session
from app.models.admin_user import AdminUser
from app.models.enums import AttendanceSession
from app.services.attendance import process_manual_entry

router = APIRouter(prefix="/attendance/manual", tags=["attendance-manual"])
templates = Jinja2Templates(directory="app/templates")

SESSION_LABELS = {AttendanceSession.SCHOOL: "School", AttendanceSession.ACADEMY: "Academy"}

_STATUS_BY_KIND = {
    "unrecognized": status.HTTP_404_NOT_FOUND,
    "inactive": status.HTTP_403_FORBIDDEN,
    "duplicate": status.HTTP_409_CONFLICT,
    "unconfigured": status.HTTP_500_INTERNAL_SERVER_ERROR,
}


@router.get("", response_class=HTMLResponse)
async def manual_attendance_page(
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
):
    return templates.TemplateResponse(
        "attendance/manual.html",
        {
            "request": request,
            "admin": admin,
            "sessions": [(s.value, SESSION_LABELS[s]) for s in AttendanceSession],
        },
    )


@router.post("")
async def manual_attendance_submit(
    identifier: str = Form(...),
    attendance_session: AttendanceSession = Form(..., alias="session"),
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    result = process_manual_entry(
        session,
        identifier=identifier.strip(),
        attendance_session=attendance_session,
        marked_by_id=admin.id,
    )
    status_code = (
        status.HTTP_200_OK
        if result.ok
        else _STATUS_BY_KIND.get(result.kind, status.HTTP_400_BAD_REQUEST)
    )
    return JSONResponse(
        {
            "ok": result.ok,
            "message": result.message,
            "person_name": result.person_name,
            "person_type": result.person_type,
            "punctuality_status": result.punctuality_status.value
            if result.punctuality_status
            else None,
            "arrival_time": result.arrival_time.strftime("%H:%M:%S")
            if result.arrival_time
            else None,
        },
        status_code=status_code,
    )