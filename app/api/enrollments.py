"""Enrollment management — Section 5 (fee & discount system) and Section 3
(admin capability: manage enrollment, apply per-student per-category
discounts). Always managed in the context of a specific student — see
students.py's student_detail route, which these all redirect back to.

Per Key Design Principle #7 (Section 13), every change here writes through
the audit-log hook — not optional. A status flip to inactive ("ending" an
enrollment) is logged as UPDATE, not DELETE — the row is never hard-deleted,
so UPDATE matches what actually happened to it.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.api.deps import get_current_admin
from app.api.students import build_student_detail_context
from app.core.database import get_session
from app.models.admin_user import AdminUser
from app.models.enrollment import Enrollment
from app.models.enums import AuditAction, DiscountType, EnrollmentStatus, FeeCategory
from app.models.student import Student
from app.services.audit import write_audit_log
from app.services.fees import get_band_fee

router = APIRouter(prefix="/students/{student_id}/enrollments", tags=["enrollments"])
templates = Jinja2Templates(directory="app/templates")


def _snapshot(enrollment: Enrollment) -> dict:
    return {
        "category": enrollment.category.value,
        "discount_type": enrollment.discount_type.value,
        "discount_value": (
            float(enrollment.discount_value) if enrollment.discount_value is not None else None
        ),
        "status": enrollment.status.value,
    }


def _parse_discount(discount_type: DiscountType, discount_value_raw: str) -> Optional[Decimal]:
    """None for DiscountType.NONE, otherwise a validated Decimal. Raises
    ValueError with a message safe to show directly to the admin."""
    if discount_type == DiscountType.NONE:
        return None

    if not discount_value_raw.strip():
        raise ValueError("Enter a discount value for a fixed or percentage discount.")

    try:
        value = Decimal(discount_value_raw)
    except InvalidOperation:
        raise ValueError("Discount value must be a number.")

    if value < 0:
        raise ValueError("Discount value can't be negative.")
    if discount_type == DiscountType.PERCENTAGE and value > 100:
        raise ValueError("A percentage discount can't exceed 100.")

    return value


def _error_response(
    request: Request,
    session: Session,
    admin: AdminUser,
    student: Student,
    message: str,
) -> HTMLResponse:
    context = build_student_detail_context(
        request, session, admin, student, enrollment_error=message
    )
    return templates.TemplateResponse(
        "students/detail.html", context, status_code=status.HTTP_400_BAD_REQUEST
    )


@router.post("")
async def create_enrollment(
    student_id: int,
    request: Request,
    category: FeeCategory = Form(...),
    discount_type: DiscountType = Form(DiscountType.NONE),
    discount_value: str = Form(""),
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    student = session.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")

    try:
        parsed_discount_value = _parse_discount(discount_type, discount_value)
    except ValueError as exc:
        return _error_response(request, session, admin, student, str(exc))

    class_offset = student.class_level.class_offset
    if get_band_fee(session, category, class_offset) is None:
        return _error_response(
            request,
            session,
            admin,
            student,
            f"{student.name}'s class level isn't eligible for {category.value} enrollment.",
        )

    enrollment = Enrollment(
        student_id=student_id,
        category=category,
        discount_type=discount_type,
        discount_value=parsed_discount_value,
        status=EnrollmentStatus.ACTIVE,
        created_by_id=admin.id,
    )
    session.add(enrollment)

    try:
        # Flush now (not just commit) so the partial unique index — one
        # active enrollment per (student, category) — surfaces here as a
        # catchable IntegrityError, and so enrollment.id exists for the
        # audit-log write below.
        session.flush()
    except IntegrityError:
        session.rollback()
        label = category.value
        return _error_response(
            request,
            session,
            admin,
            student,
            f"{student.name} already has an active enrollment in {label}.",
        )

    write_audit_log(
        session,
        admin_id=admin.id,
        action=AuditAction.CREATE,
        entity_type="Enrollment",
        entity_id=enrollment.id,
        before_value=None,
        after_value=_snapshot(enrollment),
    )
    session.commit()
    return RedirectResponse(url=f"/students/{student_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{enrollment_id}/update")
async def update_enrollment_discount(
    student_id: int,
    enrollment_id: int,
    request: Request,
    discount_type: DiscountType = Form(...),
    discount_value: str = Form(""),
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    student = session.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")

    enrollment = session.get(Enrollment, enrollment_id)
    if not enrollment or enrollment.student_id != student_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enrollment not found.")
    if enrollment.status != EnrollmentStatus.ACTIVE:
        return _error_response(
            request, session, admin, student, "Can't change the discount on an inactive enrollment."
        )

    try:
        parsed_discount_value = _parse_discount(discount_type, discount_value)
    except ValueError as exc:
        return _error_response(request, session, admin, student, str(exc))

    before = _snapshot(enrollment)
    enrollment.discount_type = discount_type
    enrollment.discount_value = parsed_discount_value
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
        after_value=_snapshot(enrollment),
    )
    session.commit()
    return RedirectResponse(url=f"/students/{student_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{enrollment_id}/end")
async def end_enrollment(
    student_id: int,
    enrollment_id: int,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    enrollment = session.get(Enrollment, enrollment_id)
    if not enrollment or enrollment.student_id != student_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enrollment not found.")

    if enrollment.status == EnrollmentStatus.ACTIVE:
        before = _snapshot(enrollment)
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
            after_value=_snapshot(enrollment),
        )
        session.commit()

    return RedirectResponse(url=f"/students/{student_id}", status_code=status.HTTP_303_SEE_OTHER)
