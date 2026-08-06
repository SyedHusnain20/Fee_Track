"""Teacher CRUD — create/edit/view/deactivate, per Section 3's admin
capabilities. Any logged-in admin can manage teachers (account management
itself stays super-admin-only, per Step 6 — this is unrelated to that).

staff_id is auto-generated (0001, 0002, ...) as of this update — no longer
a manual form field. See app.services.staff_id for the generation logic.

Phase 1 (teacher profile expansion): father_name, contact, qualification,
designation, salary, and the four teaches_* subject flags are required on
every create/update submission from here on, even though they're nullable
in the DB for the sake of teacher rows that predate this migration.

Phase 4 (School/Academy-only enrollment): the form now only collects
teaches_school and teaches_coaching ("Academy") — teaches_english and
teaches_computer are no longer exposed anywhere in the UI and are always
written as False for teachers created/edited from here on. The columns
themselves are untouched in the DB (existing rows keep whatever values
they had; no migration), they're just no longer settable. A teacher must
have at least one of teaches_school/teaches_coaching checked — enforced
here, not in the DB, matching this codebase's pattern of validating
"required going forward" fields in the API layer rather than the schema.

date_joined is no longer a form field either. It's set automatically to
school_today() on creation and left untouched on edits (it has no
UI-editable purpose once set — see app.services.teacher_salary for how
it's used).
"""

from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.deps import get_current_admin
from app.core.database import get_session
from app.core.timezone import school_today
from app.models.admin_user import AdminUser
from app.models.enums import Qualification
from app.models.teacher import Teacher
from app.services.qr_token import generate_qr_token
from app.services.staff_id import generate_staff_id
from app.services.teacher_salary import compute_teacher_monthly_salary

router = APIRouter(prefix="/teachers", tags=["teachers"])
templates = Jinja2Templates(directory="app/templates")

QUALIFICATION_LABELS = {
    Qualification.INTERMEDIATE: "Intermediate",
    Qualification.GRADUATE: "Graduate",
    Qualification.MASTERS: "Masters",
    Qualification.PHD: "PhD",
}

# Profile-page display of the teaches_* booleans — kept here rather than
# in the template so the label wording only needs to change in one place
# (matches the pattern used for FeeCategory labels in students.py).
# teaches_english/teaches_computer are deliberately excluded as of Phase 4
# (School/Academy-only enrollment) — the columns still exist for any
# legacy rows that have them set, but they're no longer part of the
# UI-facing "what does this teacher teach" story.
SUBJECTS_TAUGHT = [
    ("teaches_school", "School"),
    ("teaches_coaching", "Academy"),
]


def _parse_salary(raw: str) -> Decimal:
    """Raises ValueError with a message safe to show directly to the
    admin, matching the style of app.services.fees.parse_discount_input."""
    if not raw.strip():
        raise ValueError("Enter the teacher's salary.")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValueError("Salary must be a number.")
    if value < 0:
        raise ValueError("Salary can't be negative.")
    return value


def _parse_qualification(raw: str) -> Qualification:
    """The form renders a fixed <select> (Intermediate/Graduate/Masters/
    PhD), but we still validate server-side rather than trusting the
    submitted value, same as everywhere else in this codebase."""
    try:
        return Qualification(raw)
    except ValueError:
        raise ValueError("Select a valid qualification.")


def _require_at_least_one_category(teaches_school: bool, teaches_coaching: bool) -> None:
    """A teacher must be enrolled in School and/or Academy — there's no
    longer any other category to fall back on now that English/Computer
    are gone from the form."""
    if not teaches_school and not teaches_coaching:
        raise ValueError("Select at least one of School or Academy.")


def _form_error(
    request: Request,
    admin: AdminUser,
    teacher: Optional[Teacher],
    message: str,
) -> HTMLResponse:
    return templates.TemplateResponse(
        "teachers/form.html",
        {"request": request, "admin": admin, "teacher": teacher, "error": message},
        status_code=status.HTTP_400_BAD_REQUEST,
    )


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
    father_name: str = Form(...),
    contact: str = Form(...),
    qualification: str = Form(...),
    designation: str = Form(...),
    salary: str = Form(...),
    teaches_school: Optional[str] = Form(default=None),
    teaches_coaching: Optional[str] = Form(default=None),
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    teaches_school_value = teaches_school is not None
    teaches_coaching_value = teaches_coaching is not None

    try:
        salary_value = _parse_salary(salary)
        qualification_value = _parse_qualification(qualification)
        _require_at_least_one_category(teaches_school_value, teaches_coaching_value)
    except ValueError as exc:
        return _form_error(request, admin, None, str(exc))

    staff_id = generate_staff_id(session)

    teacher = Teacher(
        staff_id=staff_id,
        name=name.strip(),
        father_name=father_name.strip(),
        contact=contact.strip(),
        qualification=qualification_value,
        designation=designation.strip(),
        salary=salary_value,
        date_joined=school_today(),
        teaches_school=teaches_school_value,
        teaches_coaching=teaches_coaching_value,
        teaches_english=False,
        teaches_computer=False,
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


@router.get("/{teacher_id}", response_class=HTMLResponse)
async def teacher_detail(
    teacher_id: int,
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    teacher = session.get(Teacher, teacher_id)
    if not teacher:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")
    subjects = [label for field, label in SUBJECTS_TAUGHT if getattr(teacher, field)]
    salary_breakdown = compute_teacher_monthly_salary(session, teacher)
    return templates.TemplateResponse(
        "teachers/detail.html",
        {
            "request": request,
            "admin": admin,
            "teacher": teacher,
            "qualification_labels": QUALIFICATION_LABELS,
            "subjects": subjects,
            "salary_breakdown": salary_breakdown,
        },
    )


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
    father_name: str = Form(...),
    contact: str = Form(...),
    qualification: str = Form(...),
    designation: str = Form(...),
    salary: str = Form(...),
    teaches_school: Optional[str] = Form(default=None),
    teaches_coaching: Optional[str] = Form(default=None),
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    teacher = session.get(Teacher, teacher_id)
    if not teacher:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")

    teaches_school_value = teaches_school is not None
    teaches_coaching_value = teaches_coaching is not None

    try:
        salary_value = _parse_salary(salary)
        qualification_value = _parse_qualification(qualification)
        _require_at_least_one_category(teaches_school_value, teaches_coaching_value)
    except ValueError as exc:
        return _form_error(request, admin, teacher, str(exc))

    # staff_id, qr_code, and date_joined stay immutable once set — the
    # first two per Section 7's "system generates" boundary, date_joined
    # because it's no longer an editable form field (see module
    # docstring). Everything else here is editable, and saving this form
    # is what keeps the teacher's stored profile in sync with whatever
    # the admin just typed.
    teacher.name = name.strip()
    teacher.father_name = father_name.strip()
    teacher.contact = contact.strip()
    teacher.qualification = qualification_value
    teacher.designation = designation.strip()
    teacher.salary = salary_value
    teacher.teaches_school = teaches_school_value
    teacher.teaches_coaching = teaches_coaching_value
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
