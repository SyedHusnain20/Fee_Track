"""Student CRUD — create/edit/view/deactivate, per Section 3's admin
capabilities.

The detail route (`GET /students/{id}`) is also where Enrollment management
(Phase 2) and read-only fee history (Phase 3) live — both are always
managed/viewed in the context of a specific student. See
app/api/enrollments.py and app/api/fee_cycles.py for the actual mutating
routes; this file builds the shared context both render into
students/detail.html. Marking a fee cycle paid/unpaid from this page posts
to fee_cycles.py's routes directly (with next=/students/{id} so it redirects
back here instead of to the fee-cycles list).

Fee lookups here go through app.services.fees.get_band_fee, which matches
each enrollment's category against the class-level band covering the
student's current class_offset — NOT a flat per-category default (see the
fee-banding migration, f19c2a7d4b83).

Student creation (POST /students) optionally enrolls the new student in
one or more categories in the same submission (the "categories" checklist
on students/form.html) — added on top of the original create-then-enroll
two-step flow, which still works unchanged via the detail page for anyone
enrolled after creation, or in additional categories later. Category
eligibility (e.g. School's Class-10 ceiling, from the fee-banding
migration) is validated BEFORE the student row is created — an ineligible
selection creates nothing at all, rather than leaving a half-created
student with only some of the requested enrollments.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from typing_extensions import Annotated

from app.api.deps import get_current_admin
from app.core.database import get_session
from app.models.admin_user import AdminUser
from app.models.attendance_record import AttendanceRecord
from app.models.class_level import ClassLevel
from app.models.enrollment import Enrollment
from app.models.enums import AttendanceSession, AuditAction, DiscountType, EnrollmentStatus, FeeCategory
from app.models.fee_cycle import FeeCycle
from app.models.student import Student
from app.services.audit import write_audit_log
from app.services.fees import compute_enrollment_fee, get_band_fee
from app.services.qr_token import generate_qr_token
from app.services.roll_number import generate_roll_number

router = APIRouter(prefix="/students", tags=["students"])
templates = Jinja2Templates(directory="app/templates")

CATEGORY_LABELS = {
    FeeCategory.SCHOOL: "School",
    FeeCategory.COACHING: "Coaching",
    FeeCategory.ENGLISH: "English Language",
    FeeCategory.COMPUTER: "Computer Courses",
}
DISCOUNT_TYPE_LABELS = {
    DiscountType.NONE: "None",
    DiscountType.FIXED: "Fixed amount",
    DiscountType.PERCENTAGE: "Percentage",
}


def build_student_detail_context(
    request: Request,
    session: Session,
    admin: AdminUser,
    student: Student,
    enrollment_error: Optional[str] = None,
) -> dict:
    """Shared by the GET detail route below and by enrollments.py, which
    re-renders this same page (with an error message) when an enrollment
    action fails validation, instead of a bare JSON error response."""
    enrollments = session.exec(
        select(Enrollment)
        .where(Enrollment.student_id == student.id)
        .order_by(Enrollment.created_at.desc())
    ).all()
    active_enrollments = [e for e in enrollments if e.status == EnrollmentStatus.ACTIVE]
    past_enrollments = [e for e in enrollments if e.status != EnrollmentStatus.ACTIVE]

    class_offset = student.class_level.class_offset

    enrolled_categories = {e.category for e in active_enrollments}
    available_categories = [c for c in FeeCategory if c not in enrolled_categories]

    fee_rows = []
    total_fee = Decimal("0.00")
    for e in active_enrollments:
        default_amount = get_band_fee(session, e.category, class_offset) or Decimal("0.00")
        fee = compute_enrollment_fee(default_amount, e.discount_type, e.discount_value)
        total_fee += fee
        fee_rows.append({"enrollment": e, "default_amount": default_amount, "computed_fee": fee})

    fee_cycles = session.exec(
        select(FeeCycle).where(FeeCycle.student_id == student.id).order_by(FeeCycle.period.desc())
    ).all()

    # Last-7-days attendance strip, split into School and Academy rows since
    # a student can be enrolled in both simultaneously and each is tracked
    # as a separate kiosk session (see the AttendanceSession redesign).
    # Only shown for a category the student is actually enrolled in —
    # rendering an all-red strip for a category they were never enrolled
    # in would read as "absent" rather than "not applicable."
    today = date.today()
    last_7_days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]  # oldest -> newest

    show_school_attendance = any(e.category == FeeCategory.SCHOOL for e in active_enrollments)
    show_academy_attendance = any(
        e.category in (FeeCategory.COACHING, FeeCategory.ENGLISH, FeeCategory.COMPUTER)
        for e in active_enrollments
    )

    recent_attendance = []
    if show_school_attendance or show_academy_attendance:
        recent_attendance = session.exec(
            select(AttendanceRecord).where(
                AttendanceRecord.student_id == student.id,
                AttendanceRecord.scan_date >= last_7_days[0],
                AttendanceRecord.scan_date <= last_7_days[-1],
            )
        ).all()

    present_school_dates = {r.scan_date for r in recent_attendance if r.session == AttendanceSession.SCHOOL}
    present_academy_dates = {r.scan_date for r in recent_attendance if r.session == AttendanceSession.ACADEMY}

    school_attendance_strip = [{"date": d, "present": d in present_school_dates} for d in last_7_days]
    academy_attendance_strip = [{"date": d, "present": d in present_academy_dates} for d in last_7_days]

    return {
        "request": request,
        "admin": admin,
        "student": student,
        "fee_rows": fee_rows,
        "past_enrollments": past_enrollments,
        "available_categories": available_categories,
        "discount_types": list(DiscountType),
        "category_labels": CATEGORY_LABELS,
        "discount_type_labels": DISCOUNT_TYPE_LABELS,
        "total_fee": total_fee,
        "fee_cycles": fee_cycles,
        "enrollment_error": enrollment_error,
        "show_school_attendance": show_school_attendance,
        "show_academy_attendance": show_academy_attendance,
        "school_attendance_strip": school_attendance_strip,
        "academy_attendance_strip": academy_attendance_strip,
    }


@router.get("", response_class=HTMLResponse)
async def list_students(
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    students = session.exec(select(Student).order_by(Student.roll_number)).all()
    return templates.TemplateResponse(
        "students/list.html", {"request": request, "admin": admin, "students": students}
    )


@router.get("/new", response_class=HTMLResponse)
async def new_student_form(
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    class_levels = session.exec(select(ClassLevel).order_by(ClassLevel.class_offset)).all()
    return templates.TemplateResponse(
        "students/form.html",
        {
            "request": request,
            "admin": admin,
            "student": None,
            "class_levels": class_levels,
            "current_year": datetime.utcnow().year,
            "category_labels": CATEGORY_LABELS,
            "selected_categories": [],
            "error": None,
        },
    )


@router.post("")
async def create_student(
    request: Request,
    name: str = Form(...),
    father_name: str = Form(...),
    parent_whatsapp: str = Form(...),
    class_level_id: int = Form(...),
    enrollment_year: int = Form(...),
    categories: Annotated[List[FeeCategory], Form()] = [],
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    class_levels = session.exec(select(ClassLevel).order_by(ClassLevel.class_offset)).all()

    def _redisplay(error: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        return templates.TemplateResponse(
            "students/form.html",
            {
                "request": request,
                "admin": admin,
                "student": None,
                "class_levels": class_levels,
                "current_year": datetime.utcnow().year,
                "category_labels": CATEGORY_LABELS,
                "selected_categories": categories,
                "error": error,
            },
            status_code=status_code,
        )

    try:
        roll_number = generate_roll_number(
            session, class_level_id=class_level_id, enrollment_year=enrollment_year
        )
    except ValueError as exc:
        return _redisplay(str(exc))

    # Validate every selected category is eligible for this class level
    # BEFORE creating anything — an ineligible selection must not leave a
    # half-created student with only some of the requested enrollments.
    selected_categories = list(dict.fromkeys(categories))  # de-dupe, preserve order
    if selected_categories:
        class_level = session.get(ClassLevel, class_level_id)
        class_offset = class_level.class_offset if class_level else None
        ineligible = [
            c for c in selected_categories
            if class_offset is None or get_band_fee(session, c, class_offset) is None
        ]
        if ineligible:
            names = ", ".join(CATEGORY_LABELS[c] for c in ineligible)
            return _redisplay(f"This class level isn't eligible for: {names}.")

    student = Student(
        roll_number=roll_number,
        name=name.strip(),
        father_name=father_name.strip(),
        parent_whatsapp=parent_whatsapp.strip(),
        qr_code=generate_qr_token(),
        class_level_id=class_level_id,
        is_active=True,
    )
    session.add(student)
    session.flush()  # need student.id for the enrollments below

    created_enrollments = []
    for category in selected_categories:
        enrollment = Enrollment(
            student_id=student.id,
            category=category,
            discount_type=DiscountType.NONE,
            discount_value=None,
            status=EnrollmentStatus.ACTIVE,
            created_by_id=admin.id,
        )
        session.add(enrollment)
        created_enrollments.append(enrollment)

    if created_enrollments:
        session.flush()  # assign .id to each enrollment for the audit log
        for enrollment in created_enrollments:
            write_audit_log(
                session,
                admin_id=admin.id,
                action=AuditAction.CREATE,
                entity_type="Enrollment",
                entity_id=enrollment.id,
                before_value=None,
                after_value={
                    "student_id": enrollment.student_id,
                    "category": enrollment.category.value,
                    "discount_type": enrollment.discount_type.value,
                    "discount_value": None,
                    "status": enrollment.status.value,
                },
            )

    session.commit()
    return RedirectResponse(url="/students", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{student_id}", response_class=HTMLResponse)
async def student_detail(
    student_id: int,
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    student = session.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")
    context = build_student_detail_context(request, session, admin, student)
    return templates.TemplateResponse("students/detail.html", context)


@router.get("/{student_id}/edit", response_class=HTMLResponse)
async def edit_student_form(
    student_id: int,
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    student = session.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")
    class_levels = session.exec(select(ClassLevel).order_by(ClassLevel.class_offset)).all()
    return templates.TemplateResponse(
        "students/form.html",
        {
            "request": request,
            "admin": admin,
            "student": student,
            "class_levels": class_levels,
            "current_year": datetime.utcnow().year,
            "category_labels": CATEGORY_LABELS,
            "selected_categories": [],
            "error": None,
        },
    )


@router.post("/{student_id}")
async def update_student(
    student_id: int,
    name: str = Form(...),
    father_name: str = Form(...),
    parent_whatsapp: str = Form(...),
    class_level_id: int = Form(...),
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    student = session.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")

    student.name = name.strip()
    student.father_name = father_name.strip()
    student.parent_whatsapp = parent_whatsapp.strip()
    student.class_level_id = class_level_id
    session.add(student)
    session.commit()
    return RedirectResponse(url="/students", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{student_id}/deactivate")
async def deactivate_student(
    student_id: int,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    student = session.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")
    student.is_active = False
    session.add(student)
    session.commit()
    return RedirectResponse(url="/students", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{student_id}/reactivate")
async def reactivate_student(
    student_id: int,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    student = session.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")
    student.is_active = True
    session.add(student)
    session.commit()
    return RedirectResponse(url="/students", status_code=status.HTTP_303_SEE_OTHER)
