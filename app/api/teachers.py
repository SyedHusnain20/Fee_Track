"""Teacher CRUD — create/edit/view/deactivate, per Section 3's admin
capabilities. Any logged-in admin can manage teachers (account management
itself stays super-admin-only, per Step 6 — this is unrelated to that).

staff_id is auto-generated (0001, 0002, ...) as of this update — no longer
a manual form field. See app.services.staff_id for the generation logic.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.deps import get_current_admin
from app.core.database import get_session
from app.models.admin_user import AdminUser
from app.models.teacher import Teacher
from app.services.qr_token import generate_qr_token
from app.services.staff_id import generate_staff_id

router = APIRouter(prefix="/teachers", tags=["teachers"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def list_teachers(
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    teachers = session.exec(select(Teacher).order_by(Teacher.name)).all()
    return templates.TemplateResponse(
        "teachers/list.html", {"request": request, "admin": admin, "teachers": teachers}
    )


@router.get("/new", response_class=HTMLResponse)
async def new_teacher_form(
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
):
    return templates.TemplateResponse(
        "teachers/form.html", {"request": request, "admin": admin, "teacher": None, "error": None}
    )


@router.post("")
async def create_teacher(
    request: Request,
    name: str = Form(...),
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    staff_id = generate_staff_id(session)

    teacher = Teacher(
        staff_id=staff_id,
        name=name.strip(),
        qr_code=generate_qr_token(),
        is_active=True,
    )
    session.add(teacher)
    try:
        session.commit()
    except IntegrityError:
        # Extremely rare: two teachers created in the same instant both
        # computed the same next number before either committed. Fails
        # loudly rather than silently — just ask the admin to retry, which
        # will compute a fresh MAX() and succeed.
        session.rollback()
        return templates.TemplateResponse(
            "teachers/form.html",
            {
                "request": request,
                "admin": admin,
                "teacher": None,
                "error": "Staff ID generation collided with another request — please try again.",
            },
            status_code=status.HTTP_409_CONFLICT,
        )
    return RedirectResponse(url="/teachers", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{teacher_id}/edit", response_class=HTMLResponse)
async def edit_teacher_form(
    teacher_id: int,
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    teacher = session.get(Teacher, teacher_id)
    if not teacher:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")
    return templates.TemplateResponse(
        "teachers/form.html",
        {
            "request": request,
            "admin": admin,
            "teacher": teacher,
            "error": None,
        },
    )


@router.post("/{teacher_id}")
async def update_teacher(
    teacher_id: int,
    request: Request,
    name: str = Form(...),
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    teacher = session.get(Teacher, teacher_id)
    if not teacher:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")

    # staff_id and qr_code are immutable once generated — only name is
    # editable here, matching Section 7's "system generates" boundary.
    teacher.name = name.strip()
    session.add(teacher)
    session.commit()
    return RedirectResponse(url="/teachers", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{teacher_id}/deactivate")
async def deactivate_teacher(
    teacher_id: int,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    teacher = session.get(Teacher, teacher_id)
    if not teacher:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")
    teacher.is_active = False
    session.add(teacher)
    session.commit()
    return RedirectResponse(url="/teachers", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{teacher_id}/reactivate")
async def reactivate_teacher(
    teacher_id: int,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    teacher = session.get(Teacher, teacher_id)
    if not teacher:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")
    teacher.is_active = True
    session.add(teacher)
    session.commit()
    return RedirectResponse(url="/teachers", status_code=status.HTTP_303_SEE_OTHER)
