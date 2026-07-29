"""Academic year rollover — Step 11. Manual, admin-triggered: GET /rollover
shows a preview (how many students promote per class, how many Class 12
students will be deactivated as graduating) computed live against current
data; POST /rollover/execute is the confirm step that actually commits the
promotion. No scheduling, no double-run lockout — trusted to the admin's
judgment on when to run it, per spec.

Scope, decided explicitly: only Student.class_level_id (promotion) and
Student.is_active (graduating Class 12 -> deactivated) are touched.
roll_number is permanent and never changes. Enrollment and FeeCycle are
completely untouched by rollover — both continue as-is into the new year;
if an Enrollment needs to end/renew, that's a separate admin action via
students.py/enrollments.py, not something rollover does automatically.

Restricted to require_super_admin — only reachable via /settings, and
only visible in the navbar to super admins, per explicit access-control
decision (same treatment as /settings and /category-fees).
"""

from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.api.deps import require_super_admin
from app.core.database import get_session
from app.models.admin_user import AdminUser
from app.models.class_level import ClassLevel
from app.models.enums import AuditAction
from app.models.student import Student
from app.services.audit import write_audit_log

router = APIRouter(prefix="/rollover", tags=["rollover"])
templates = Jinja2Templates(directory="app/templates")


def _next_level_map(class_levels: list[ClassLevel]) -> dict[int, Optional[ClassLevel]]:
    """Maps each ClassLevel.id -> the ClassLevel one offset higher, or None
    if it's the highest offset (Class 12 — graduating, nothing to promote
    to). Relies on class_offset being contiguous, which
    scripts/seed_reference_data.py guarantees (Foundation 1-3 -> 0-2,
    Class 1-12 -> 3-14)."""
    by_offset = {cl.class_offset: cl for cl in class_levels}
    return {cl.id: by_offset.get(cl.class_offset + 1) for cl in class_levels}


def _build_preview(session: Session) -> dict:
    class_levels = session.exec(select(ClassLevel).order_by(ClassLevel.class_offset)).all()
    next_level = _next_level_map(class_levels)

    students = session.exec(select(Student).where(Student.is_active == True)).all()  # noqa: E712

    counts_by_level: dict[int, int] = {}
    for student in students:
        counts_by_level[student.class_level_id] = counts_by_level.get(student.class_level_id, 0) + 1

    rows = []  # [{from_level, to_level_or_None, count}]
    total_promoted = 0
    total_graduating = 0
    for cl in class_levels:
        count = counts_by_level.get(cl.id, 0)
        if count == 0:
            continue
        to_level = next_level.get(cl.id)
        rows.append({"from_level": cl, "to_level": to_level, "count": count})
        if to_level is None:
            total_graduating += count
        else:
            total_promoted += count

    return {
        "rows": rows,
        "total_promoted": total_promoted,
        "total_graduating": total_graduating,
        "total_active": len(students),
    }


@router.get("", response_class=HTMLResponse)
async def rollover_preview(
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(require_super_admin),
):
    preview = _build_preview(session)
    return templates.TemplateResponse(
        "rollover/preview.html",
        {"request": request, "admin": admin, **preview, "done": False},
    )


@router.post("/execute")
async def rollover_execute(
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(require_super_admin),
):
    class_levels = session.exec(select(ClassLevel).order_by(ClassLevel.class_offset)).all()
    next_level = _next_level_map(class_levels)

    students = session.exec(select(Student).where(Student.is_active == True)).all()  # noqa: E712

    promoted_count = 0
    graduated_count = 0

    for student in students:
        to_level = next_level.get(student.class_level_id)
        before = {"class_level_id": student.class_level_id, "is_active": student.is_active}

        if to_level is None:
            # Class 12 — graduating, no further level to promote to.
            student.is_active = False
            graduated_count += 1
        else:
            student.class_level_id = to_level.id
            promoted_count += 1

        session.add(student)
        write_audit_log(
            session,
            admin_id=admin.id,
            action=AuditAction.UPDATE,
            entity_type="Student",
            entity_id=student.id,
            before_value=before,
            after_value={"class_level_id": student.class_level_id, "is_active": student.is_active},
        )

    session.commit()

    preview = _build_preview(session)
    return templates.TemplateResponse(
        "rollover/preview.html",
        {
            "request": request,
            "admin": admin,
            **preview,
            "done": True,
            "result_promoted": promoted_count,
            "result_graduated": graduated_count,
        },
    )
