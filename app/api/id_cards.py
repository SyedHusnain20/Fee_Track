"""QR code images and printable ID cards — Step 8.

Kept as its own router rather than folded into students.py/teachers.py:
both entities need near-identical qr-code.png + id-card handling, and
neither is really "CRUD" — this is display/rendering, a different concern.

QR images and ID cards require the same admin login as everything else
(not left open) — the <img> tags that use them sit on already-authenticated
admin pages, and same-site image requests carry the session cookie fine
under SameSite=Lax, so this doesn't break anything, it just keeps the
tokens from being fetchable by an unauthenticated request.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.api.deps import get_current_admin
from app.core.database import get_session
from app.models.admin_user import AdminUser
from app.models.student import Student
from app.models.teacher import Teacher
from app.services.qr_image import render_qr_png

router = APIRouter(tags=["id-cards"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/students/{student_id}/qr-code.png")
async def student_qr_png(
    student_id: int,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    student = session.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")
    return Response(content=render_qr_png(student.qr_code), media_type="image/png")


@router.get("/students/{student_id}/id-card", response_class=HTMLResponse)
async def student_id_card(
    student_id: int,
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    student = session.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")
    return templates.TemplateResponse(
        "id_cards/student_card.html", {"request": request, "student": student}
    )


@router.get("/teachers/{teacher_id}/qr-code.png")
async def teacher_qr_png(
    teacher_id: int,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    teacher = session.get(Teacher, teacher_id)
    if not teacher:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")
    return Response(content=render_qr_png(teacher.qr_code), media_type="image/png")


@router.get("/teachers/{teacher_id}/id-card", response_class=HTMLResponse)
async def teacher_id_card(
    teacher_id: int,
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    teacher = session.get(Teacher, teacher_id)
    if not teacher:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")
    return templates.TemplateResponse(
        "id_cards/teacher_card.html", {"request": request, "teacher": teacher}
    )
