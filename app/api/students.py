"""Student CRUD — create/edit/view/deactivate, per Section 3's admin
capabilities.

Category enrollment (which categories a student is enrolled in, discounts)
is deliberately NOT handled here — that's Phase 2 of Step 7, its own
Enrollment-focused UI. A Student can exist with zero active enrollments
between being created and being enrolled; nothing in the schema requires
otherwise.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.api.deps import get_current_admin
from app.core.database import get_session
from app.models.admin_user import AdminUser
from app.models.class_level import ClassLevel
from app.models.student import Student
from app.services.qr_token import generate_qr_token
from app.services.roll_number import generate_roll_number

router = APIRouter(prefix="/students", tags=["students"])
templates = Jinja2Templates(directory="app/templates")


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

    # roll_number and qr_code are immutable once generated — system-
    # generated identifiers never get admin-edited (Section 7 boundary).
    # class_level_id IS editable (a student can be promoted/moved), but that
    # deliberately does NOT retroactively regenerate the roll number — the
    # cohort code reflects the year+level they were admitted under.
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
