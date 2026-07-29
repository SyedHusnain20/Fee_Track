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
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import Session, or_, select
from typing_extensions import Annotated

from app.api.deps import get_current_admin
from app.core.database import get_session
from app.core.timezone import school_today
from app.models.admin_user import AdminUser
from app.models.attendance_record import AttendanceRecord
from app.models.category_fee_default import CategoryFeeDefault
from app.models.class_level import ClassLevel
from app.models.enrollment import Enrollment
from app.models.enums import (
    AttendanceSession,
    AuditAction,
    DiscountType,
    EnrollmentStatus,
    FeeCategory,
    FeeCycleStatus,
)
from app.models.fee_cycle import FeeCycle
from app.models.student import Student
from app.services.audit import write_audit_log
from app.services.fee_settings import get_fee_due_day
from app.services.fees import (
    apply_discount,
    compute_student_fee_breakdown,
    get_band_fee,
    parse_discount_input,
)
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
# Compact per-student category code shown on /students -- e.g. a student
# enrolled in Coaching + Computer shows "AC". Always rendered in this
# fixed S/A/L/C order (matching FeeCategory's own enum order) regardless
# of which ones are present, so the code is scannable/consistent across
# rows rather than shuffling letter order per student.
CATEGORY_CODE = {
    FeeCategory.SCHOOL: "S",
    FeeCategory.COACHING: "A",
    FeeCategory.ENGLISH: "L",
    FeeCategory.COMPUTER: "C",
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

    enrolled_categories = {e.category for e in active_enrollments}
    available_categories = [c for c in FeeCategory if c not in enrolled_categories]

    fee_breakdown = compute_student_fee_breakdown(session, student)
    fee_rows = [
        {
            "enrollment": e,
            "default_amount": fee_breakdown["category_amounts"].get(e.category, Decimal("0.00")),
        }
        for e in active_enrollments
    ]

    fee_cycles = session.exec(
        select(FeeCycle).where(FeeCycle.student_id == student.id).order_by(FeeCycle.period.desc())
    ).all()

    # Last-7-days attendance strip, split into School and Academy rows since
    # a student can be enrolled in both simultaneously and each is tracked
    # as a separate kiosk session (see the AttendanceSession redesign).
    # Only shown for a category the student is actually enrolled in —
    # rendering an all-red strip for a category they were never enrolled
    # in would read as "absent" rather than "not applicable."
    today = school_today()
    last_7_days = [
            today - timedelta(days=offset) 
            for offset in range(6, -1, -1)
    ]# oldest -> newest

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

    present_school_dates = {
        r.scan_date 
        for r in recent_attendance 
        if r.session == AttendanceSession.SCHOOL
    }
    present_academy_dates = {
        r.scan_date 
        for r in recent_attendance 
        if r.session == AttendanceSession.ACADEMY
    }

    school_attendance_strip = [
        {
            "date": d, 
            "present": d in present_school_dates
        } 
        for d in last_7_days
    ]
    academy_attendance_strip = [
        {
            "date": d, 
            "present": d in present_academy_dates
        } 
            for d in last_7_days
    ]

    return {
        "request": request,
        "admin": admin,
        "student": student,
        "fee_rows": fee_rows,
        "past_enrollments": past_enrollments,
        "available_categories": available_categories,
        "category_labels": CATEGORY_LABELS,
        "discount_type_labels": DISCOUNT_TYPE_LABELS,
        "fee_subtotal": fee_breakdown["subtotal"],
        "discount_amount": fee_breakdown["discount_amount"],
        "total_fee": fee_breakdown["final_total"],
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
    search: Optional[str] = None,
    group: Optional[str] = None,  # "school" | "academy" | None (All)
    class_level_id: Optional[str] = None,  # str, not int -- see conversion below
    page: int = 1,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    """Paginated, and bulk-fetches fee bands + enrollments + this month's
    fee cycles for the current page instead of querying per-student —
    the previous version called compute_student_total_fee() once per row,
    which itself ran a fresh query per enrollment to find its fee band.
    At real school scale (hundreds-to-low-thousands of students) that was
    thousands of extra round-trips on a single page load. This version
    runs a small, fixed number of queries regardless of how many students
    are shown.
    """
    PAGE_SIZE = 50

    # FastAPI would reject class_level_id="" (the "All classes" <option>'s
    # empty value) outright if this were typed as Optional[int] -- an empty
    # string isn't a valid int, so automatic parsing 422s before this
    # function even runs. Same class of bug as reports.py's session filter.
    # Accept it as a string and convert manually instead, treating empty as
    # "no filter."
    class_level_id_int: Optional[int] = None
    if class_level_id:
        try:
            class_level_id_int = int(class_level_id)
        except ValueError:
            class_level_id_int = None

    if page < 1:
        page = 1

    base_query = select(Student)

    search_term = (search or "").strip()
    if search_term:
        like = f"%{search_term}%"
        base_query = base_query.where(
            or_(
                Student.name.ilike(like), 
                Student.roll_number.ilike(like)
            )
        )

    if class_level_id_int:
        base_query = base_query.where(Student.class_level_id == class_level_id_int)

    # School/Academy is not a column on Student — it's derived from whether
    # the student has an ACTIVE enrollment in the matching category set.
    # This is also what makes "the same roll number reappears under a
    # different category filter" work for free: a student enrolled in both
    # School and Coaching simply matches both filters, since it's the same
    # row being filtered, not duplicated.
    if group == "school":
        matching_ids = select(Enrollment.student_id).where(
            Enrollment.category == FeeCategory.SCHOOL,
            Enrollment.status == EnrollmentStatus.ACTIVE,
        )
        base_query = base_query.where(Student.id.in_(matching_ids))
    elif group == "academy":
        matching_ids = select(Enrollment.student_id).where(
            Enrollment.category.in_(
                [
                    FeeCategory.COACHING, 
                    FeeCategory.ENGLISH, 
                    FeeCategory.COMPUTER
                ]
            ),
            Enrollment.status == EnrollmentStatus.ACTIVE,
        )
        base_query = base_query.where(Student.id.in_(matching_ids))

    # Total count for pagination, from the SAME filtered query (before
    # order/limit/offset) so it reflects exactly what's being paginated —
    # verified this subquery-count pattern works correctly beforehand.
    total_count = session.exec(select(func.count()).select_from(base_query.subquery())).one()
    total_pages = max(1, (total_count + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages)

    # selectinload(Student.class_level): without this, student.class_level.name
    # in the template lazy-loads the class level ONE ROW AT A TIME — an N+1
    # that's existed since the original build, separate from the fee one.
    # This fetches all needed class levels in a single extra query instead.
    page_query = (
        base_query
        .options(selectinload(Student.class_level))
        .order_by(Student.roll_number)
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )
    students = session.exec(page_query).all()

    class_levels = session.exec(select(ClassLevel).order_by(ClassLevel.class_offset)).all()

    page_student_ids = [s.id for s in students]

    # Bulk fee-band lookup: fetch all 11 bands ONCE, build an in-memory
    # lookup, and match each enrollment's category+class_offset in pure
    # Python — no per-enrollment query, unlike get_band_fee() when called
    # in a loop.
    all_bands = session.exec(select(CategoryFeeDefault)).all()
    bands_by_category: dict = {}
    for band in all_bands:
        bands_by_category.setdefault(band.category, []).append(band)

    def _band_fee(category: FeeCategory, class_offset: int) -> Decimal:
        for band in bands_by_category.get(category, []):
            if band.min_class_offset <= class_offset <= band.max_class_offset:
                return band.default_amount
        return Decimal("0.00")

    # Bulk enrollment fetch for just this page's students, one query.
    enrollments_by_student: dict = {}
    if page_student_ids:
        page_enrollments = session.exec(
            select(Enrollment).where(
                Enrollment.student_id.in_(page_student_ids),
                Enrollment.status == EnrollmentStatus.ACTIVE,
            )
        ).all()
        for e in page_enrollments:
            enrollments_by_student.setdefault(e.student_id, []).append(e)

    # Overdue-fee highlighting, scoped to just this page's students now
    # that the list is paginated. After the configured due day of the
    # month (admin-editable on /settings, defaults to 10 — see
    # app.services.fee_settings), a student with an actual fee obligation
    # (total_fee > 0) is flagged red if this month's FeeCycle either
    # doesn't exist yet or exists but isn't paid. Only applies to active
    # students.
    today = school_today()
    due_day = get_fee_due_day(session)
    is_past_due_day = today.day > due_day
    current_period = f"{today.year:04d}-{today.month:02d}"
    cycle_by_student: dict = {}
    if page_student_ids:
        cycles_this_period = session.exec(
            select(FeeCycle).where(
                FeeCycle.period == current_period,
                FeeCycle.student_id.in_(page_student_ids),
            )
        ).all()
        cycle_by_student = {c.student_id: c for c in cycles_this_period}

    rows = []
    for student in students:
        class_offset = student.class_level.class_offset
        student_enrollments = enrollments_by_student.get(student.id, [])
        subtotal = Decimal("0.00")
        for e in student_enrollments:
            subtotal += _band_fee(e.category, class_offset)
        total_fee = apply_discount(subtotal, student.discount_type, student.discount_value)

        categories_present = {
            e.category for e in student_enrollments
        }
        category_code = "".join(
            CATEGORY_CODE[c] 
            for c in FeeCategory 
            if c in categories_present
        )
        category_tooltip = ", ".join(
            CATEGORY_LABELS[c] 
            for c in FeeCategory 
            if c in categories_present
        )

        cycle = cycle_by_student.get(student.id)
        is_overdue = (
            student.is_active
            and total_fee > Decimal("0.00")
            and is_past_due_day
            and (cycle is None or cycle.status != FeeCycleStatus.PAID)
        )
        # Fee Status column: plain "is this month's cycle paid?" — distinct
        # from is_overdue above, which additionally requires being past the
        # configured due day and actually owing money before it turns the
        # row red. A student can show "Unpaid" here before the due day
        # without the row being highlighted yet. Per explicit decision: a
        # student with no active enrollments never gets a FeeCycle
        # generated at all (fee_cycle_generation.py skips zero-due students
        # outright), so they show "Unpaid" permanently rather than "N/A" —
        # intentional, not a bug.
        fee_status = "Paid" if (
            cycle is not None and cycle.status == FeeCycleStatus.PAID
        ) else "Unpaid"
        rows.append({
            "student": student,
            "total_fee": total_fee,
            "is_overdue": is_overdue,
            "fee_status": fee_status,
            "category_code": category_code,
            "category_tooltip": category_tooltip,
        })

    return templates.TemplateResponse(
        "students/list.html",
        {
            "request": request,
            "admin": admin,
            "rows": rows,
            "class_levels": class_levels,
            "search": search_term,
            "group": group or "",
            "class_level_id": class_level_id_int,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "due_day": due_day,
        },
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
            "discount_type_labels": DISCOUNT_TYPE_LABELS,
            "discount_types": list(DiscountType),
            "selected_categories": [],
            "submitted_discount_type": DiscountType.NONE,
            "submitted_discount_value": "",
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
    discount_type: DiscountType = Form(DiscountType.NONE),
    discount_value: str = Form(""),
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
                "discount_type_labels": DISCOUNT_TYPE_LABELS,
                "discount_types": list(DiscountType),
                "selected_categories": categories,
                "submitted_discount_type": discount_type,
                "submitted_discount_value": discount_value,
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

    # One overall discount per student, set here at creation time (or
    # later via the edit form) — not per category. See app/services/fees.py.
    try:
        parsed_discount_value = parse_discount_input(discount_type, discount_value)
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
        discount_type=discount_type,
        discount_value=parsed_discount_value,
    )
    session.add(student)
    session.flush()  # need student.id for the enrollments below

    created_enrollments = []
    for category in selected_categories:
        enrollment = Enrollment(
            student_id=student.id,
            category=category,
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
            "discount_type_labels": DISCOUNT_TYPE_LABELS,
            "discount_types": list(DiscountType),
            "selected_categories": [],
            "submitted_discount_type": student.discount_type,
            "submitted_discount_value": (
                str(student.discount_value) if student.discount_value is not None else ""
            ),
            "error": None,
        },
    )


@router.post("/{student_id}")
async def update_student(
    student_id: int,
    request: Request,
    name: str = Form(...),
    father_name: str = Form(...),
    parent_whatsapp: str = Form(...),
    class_level_id: int = Form(...),
    discount_type: DiscountType = Form(DiscountType.NONE),
    discount_value: str = Form(""),
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    student = session.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")

    try:
        parsed_discount_value = parse_discount_input(discount_type, discount_value)
    except ValueError as exc:
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
                "discount_type_labels": DISCOUNT_TYPE_LABELS,
                "discount_types": list(DiscountType),
                "selected_categories": [],
                "submitted_discount_type": discount_type,
                "submitted_discount_value": discount_value,
                "error": str(exc),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    student.name = name.strip()
    student.father_name = father_name.strip()
    student.parent_whatsapp = parent_whatsapp.strip()
    student.class_level_id = class_level_id
    student.discount_type = discount_type
    student.discount_value = parsed_discount_value
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
