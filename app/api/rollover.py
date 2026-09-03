"""Academic year rollover — Step 11. Manual, admin-triggered: GET /rollover
shows a preview (how many students promote per class, how many School/
Coaching enrollments will auto-end) computed live against current data;
POST /rollover/execute is the confirm step that actually commits it. No
scheduling, no double-run lockout — trusted to the admin's judgment on
when to run it, per spec.

Scope, revised from the original whole-student-graduation design:

  - Student.class_level_id promotes by exactly one level for every active
    student, same as before. Reaching the top of the currently-defined
    class ladder (whatever the highest class_offset is) no longer
    deactivates the student — it just means there's nothing to promote
    them into this run, so class_level_id is left as-is.

  - Whether a student's PROGRAM ends at a given class is a per-category
    question now, not a whole-student one, answered by comparing the
    student's class BEFORE promotion against how far that category's own
    CategoryFeeDefault bands reach: School stops at Class 10, Coaching at
    Class 12 (today's seeded bands — see scripts/seed_reference_data.py —
    but read live from the DB here, not hardcoded, so this stays correct
    if those bands are ever reconfigured on /category-fees). A student at
    or past that class when rollover runs has their School/Coaching
    enrollment set to INACTIVE; every other active enrollment (English,
    Computer, or School/Coaching enrollments not yet at their category's
    ceiling) is untouched.

  - English and Computer enrollments are NEVER auto-ended by rollover,
    full stop — per explicit decision, they "don't care about classes"
    (their CategoryFeeDefault band is a single flat 0-14 "All classes"
    row) and admins end them manually via students.py/enrollments.py.
    ROLLOVER_MANAGED_CATEGORIES below is the one place that exclusion
    lives.

  - FeeCycle is completely untouched by rollover, same as before — it
    continues as-is into the new year.

Restricted to require_super_admin — only reachable via /settings, and
only visible in the navbar to super admins, per explicit access-control
decision (same treatment as /settings and /category-fees).
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import selectinload
from sqlmodel import Session, func, select

from app.api.deps import require_super_admin
from app.core.database import get_session
from app.models.admin_user import AdminUser
from app.models.category_fee_default import CategoryFeeDefault
from app.models.class_level import ClassLevel
from app.models.enrollment import Enrollment
from app.models.enums import AuditAction, EnrollmentStatus, FeeCategory
from app.models.student import Student
from app.services.audit import write_audit_log

router = APIRouter(prefix="/rollover", tags=["rollover"])
templates = Jinja2Templates(directory="app/templates")

ROLLOVER_MANAGED_CATEGORIES = (FeeCategory.SCHOOL, FeeCategory.COACHING)


def _next_level_map(class_levels: list[ClassLevel]) -> dict[int, Optional[ClassLevel]]:
    """Maps each ClassLevel.id -> the ClassLevel one offset higher, or None
    if it's the highest class_offset currently defined. Relies on
    class_offset being contiguous (scripts/seed_reference_data.py
    guarantees this: Foundation 1-3 -> 0-2, Class 1-12 -> 3-14)."""
    by_offset = {cl.class_offset: cl for cl in class_levels}
    return {cl.id: by_offset.get(cl.class_offset + 1) for cl in class_levels}


def _category_max_offsets(session: Session) -> dict[FeeCategory, int]:
    """The highest class_offset each rollover-managed category's fee bands
    actually cover -- the last class a student can be enrolled in that
    category for. A category with no CategoryFeeDefault rows at all
    (shouldn't happen in practice, but defensively) is simply absent from
    the result and never triggers an ending."""
    rows = session.exec(
        select(CategoryFeeDefault.category, func.max(CategoryFeeDefault.max_class_offset))
        .where(CategoryFeeDefault.category.in_(ROLLOVER_MANAGED_CATEGORIES))
        .group_by(CategoryFeeDefault.category)
    ).all()
    return dict(rows)


def _enrollments_to_end(session: Session, max_offsets: dict[FeeCategory, int]) -> list[Enrollment]:
    """Active School/Coaching enrollments whose student is currently AT or
    past that category's max covered class -- evaluated against the
    student's CURRENT class (before this run's promotion), since that's
    the class they're finishing, not the one they're about to enter."""
    if not max_offsets:
        return []

    candidates = session.exec(
        select(Enrollment)
        .options(selectinload(Enrollment.student).selectinload(Student.class_level))
        .where(
            Enrollment.status == EnrollmentStatus.ACTIVE,
            Enrollment.category.in_(max_offsets.keys()),
        )
    ).all()

    return [
        enrollment
        for enrollment in candidates
        if enrollment.student.is_active
        and enrollment.student.class_level.class_offset >= max_offsets[enrollment.category]
    ]


def _build_preview(session: Session) -> dict:
    class_levels = session.exec(select(ClassLevel).order_by(ClassLevel.class_offset)).all()
    next_level = _next_level_map(class_levels)
    max_offsets = _category_max_offsets(session)

    students = session.exec(select(Student).where(Student.is_active == True)).all()  # noqa: E712

    counts_by_level: dict[int, int] = {}
    for student in students:
        counts_by_level[student.class_level_id] = counts_by_level.get(student.class_level_id, 0) + 1

    rows = []  # [{from_level, to_level_or_None, count}]
    total_promoted = 0
    total_at_top = 0
    for cl in class_levels:
        count = counts_by_level.get(cl.id, 0)
        if count == 0:
            continue
        to_level = next_level.get(cl.id)
        rows.append({"from_level": cl, "to_level": to_level, "count": count})
        if to_level is None:
            total_at_top += count
        else:
            total_promoted += count

    ending = _enrollments_to_end(session, max_offsets)
    ending_counts = {category: 0 for category in ROLLOVER_MANAGED_CATEGORIES}
    for enrollment in ending:
        ending_counts[enrollment.category] += 1

    return {
        "rows": rows,
        "total_promoted": total_promoted,
        "total_at_top": total_at_top,
        "total_active": len(students),
        "total_school_ending": ending_counts[FeeCategory.SCHOOL],
        "total_coaching_ending": ending_counts[FeeCategory.COACHING],
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
    max_offsets = _category_max_offsets(session)

    # Enrollment endings are decided and applied FIRST, against each
    # student's class BEFORE promotion -- a Class 10 School enrollment
    # ends because the student finished Class 10, not because of whatever
    # class they're about to be promoted into.
    ending = _enrollments_to_end(session, max_offsets)
    ending_counts = {category: 0 for category in ROLLOVER_MANAGED_CATEGORIES}
    for enrollment in ending:
        before = {"category": enrollment.category.value, "status": enrollment.status.value}
        enrollment.status = EnrollmentStatus.INACTIVE
        enrollment.updated_by_id = admin.id
        enrollment.updated_at = datetime.utcnow()
        session.add(enrollment)
        write_audit_log(
            session,
            admin_id=admin.id,
            action=AuditAction.UPDATE,
            entity_type="Enrollment",
            entity_id=enrollment.id,
            before_value=before,
            after_value={"category": enrollment.category.value, "status": enrollment.status.value},
        )
        ending_counts[enrollment.category] += 1

    students = session.exec(select(Student).where(Student.is_active == True)).all()  # noqa: E712

    promoted_count = 0
    at_top_count = 0

    for student in students:
        to_level = next_level.get(student.class_level_id)
        if to_level is None:
            # Nothing currently defined above this class -- leave as-is.
            # This is no longer treated as graduation (see module
            # docstring): a student sitting at the top of the ladder may
            # still have an active English/Computer enrollment rollover
            # has no opinion about.
            at_top_count += 1
            continue

        before = {"class_level_id": student.class_level_id}
        student.class_level_id = to_level.id
        session.add(student)
        write_audit_log(
            session,
            admin_id=admin.id,
            action=AuditAction.UPDATE,
            entity_type="Student",
            entity_id=student.id,
            before_value=before,
            after_value={"class_level_id": student.class_level_id},
        )
        promoted_count += 1

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
            "result_at_top": at_top_count,
            "result_school_ending": ending_counts[FeeCategory.SCHOOL],
            "result_coaching_ending": ending_counts[FeeCategory.COACHING],
        },
    )
