"""Attendance archive & reset — the actual documented Step 11 (Section 4):
export all live AttendanceRecord data to Excel, upload to B2, and only
clear AttendanceRecord if that upload is confirmed successful. Manual,
admin-triggered, same preview-then-confirm pattern as rollover.py.

Not restricted to super-admin: Section 3 states attendance capabilities
are "equal across all three admins."

Distinct from app/api/rollover.py (class promotion) — that's a separate,
real feature that ended up built under the "Step 11" nickname earlier in
this project by mistake; this module is the one the spec actually means.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.api.deps import get_current_admin
from app.core.database import get_session
from app.models.admin_user import AdminUser
from app.models.attendance_record import AttendanceRecord
from app.models.enums import AuditAction
from app.services.attendance_archive import build_workbook, get_archive_summary
from app.services.audit import write_audit_log
from app.services.b2_upload import B2UploadError, upload_archive_to_b2

router = APIRouter(prefix="/archive", tags=["archive"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def archive_preview(
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    summary = get_archive_summary(session)
    return templates.TemplateResponse(
        "archive/preview.html",
        {"request": request, "admin": admin, **summary, "done": False, "error": None},
    )


@router.post("/execute")
async def archive_execute(
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    summary = get_archive_summary(session)

    if summary["total"] == 0:
        return templates.TemplateResponse(
            "archive/preview.html",
            {
                "request": request,
                "admin": admin,
                **summary,
                "done": False,
                "error": "Nothing to archive — AttendanceRecord is already empty.",
            },
        )

    workbook = build_workbook(session)
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    remote_filename = (
        f"attendance-archives/{summary['start_date']}_to_{summary['end_date']}_{timestamp}.xlsx"
    )

    try:
        file_id = upload_archive_to_b2(workbook, remote_filename)
    except B2UploadError as exc:
        return templates.TemplateResponse(
            "archive/preview.html",
            {
                "request": request,
                "admin": admin,
                **summary,
                "done": False,
                "error": f"Upload failed — AttendanceRecord was NOT cleared. {exc}",
            },
        )

    # Only past this point is the B2 upload confirmed successful.
    write_audit_log(
        session,
        admin_id=admin.id,
        action=AuditAction.DELETE,
        entity_type="AttendanceArchive",
        entity_id=0,  # bulk/table-wide action, not a single row — flagging
        # this as an assumption since write_audit_log's exact signature/
        # typing wasn't reconfirmed for this non-standard case.
        before_value={
            "total_records": summary["total"],
            "start_date": str(summary["start_date"]),
            "end_date": str(summary["end_date"]),
            "b2_file_id": file_id,
            "b2_filename": remote_filename,
        },
        after_value={"total_records": 0},
    )

    records = session.exec(select(AttendanceRecord)).all()
    for record in records:
        session.delete(record)
    session.commit()

    return templates.TemplateResponse(
        "archive/preview.html",
        {
            "request": request,
            "admin": admin,
            "total": 0,
            "start_date": None,
            "end_date": None,
            "class_counts": [],
            "teacher_count": 0,
            "done": True,
            "result_archived": summary["total"],
            "result_filename": remote_filename,
            "error": None,
        },
    )
