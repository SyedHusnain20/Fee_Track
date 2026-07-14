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
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.api.deps import get_current_admin
from app.core.database import get_session
from app.models.admin_user import AdminUser
from app.models.category_fee_default import CategoryFeeDefault
from app.models.class_level import ClassLevel
from app.models.enrollment import Enrollment
from app.models.enums import DiscountType, EnrollmentStatus, FeeCategory
from app.models.fee_cycle import FeeCycle
from app.models.student import Student
from app.services.fees import compute_enrollment_fee
from app.services.qr_token import generate_qr_token
from app.services.roll_number import generate_roll_number

router = APIRouter(prefix="/students", tags=["students"])
templates = Jinja2Templates(directory="app/templates")

# Display labels — spec (Section 2) spells "English Language" and "Computer
# Courses" out in full; the enum .values are the short DB-facing strings.
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

    category_defaults = {
        row.category: row.default_amount for row in session.exec(select(CategoryFeeDefault)).all()
    }

    enrolled_categories = {e.category for e in active_enrollments}
    available_categories = [c for c in FeeCategory if c not in enrolled_categories]

    fee_rows = []
    total_fee = Decimal("0.00")
    for e in active_enrollments:
        default_amount = category_defaults.get(e.category, Decimal("0.00"))
        fee = compute_enrollment_fee(default_amount, e.discount_type, e.discount_value)
        total_fee += fee
        fee_rows.append({"enrollment": e, "default_amount": default_amount, "computed_fee": fee})

    fee_cycles = session.exec(
        select(FeeCycle).where(FeeCycle.student_id == student.id).order_by(FeeCycle.period.desc())
    ).all()

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
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    try:
        roll_number = generate_roll_number(
            session, class_level_id=class_level_id, enrollment_year=enrollment_year
        )
    except ValueError as exc:
        class_levels = session.exec(select(ClassLevel).order_by(ClassLevel.class_offset)).all()
        return templates.TemplateResponse(
            "students/form.html",
            {
                "request": request,
                "admin": admin,
                "student": None,
                "class_levels": class_levels,
                "current_year": datetime.utcnow().year,
                "error": str(exc),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

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
