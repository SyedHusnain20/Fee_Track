"""Public attendance kiosk — Step 9. Unauthenticated by design: "the
attendance kiosk is not a role... physically secured at the school gate."
No get_current_admin anywhere in this file — that's intentional, not an
oversight.
"""
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.core.database import get_session
from app.models.enums import FeeCategory
from app.services.attendance import process_scan

router = APIRouter(prefix="/kiosk", tags=["kiosk"])
templates = Jinja2Templates(directory="app/templates")

CATEGORY_LABELS = {
    FeeCategory.SCHOOL: "School",
    FeeCategory.COACHING: "Coaching",
    FeeCategory.ENGLISH: "English Language",
    FeeCategory.COMPUTER: "Computer Courses",
}

_STATUS_BY_KIND = {
    "unrecognized": status.HTTP_404_NOT_FOUND,
    "inactive": status.HTTP_403_FORBIDDEN,
    "duplicate": status.HTTP_409_CONFLICT,
    "unconfigured": status.HTTP_500_INTERNAL_SERVER_ERROR,
}


@router.get("", response_class=HTMLResponse)
async def kiosk_page(request: Request):
    return templates.TemplateResponse(
        "kiosk/scan.html",
        {"request": request, "categories": [(c.value, CATEGORY_LABELS[c]) for c in FeeCategory]},
    )


@router.post("/scan")
async def scan(
    token: str = Form(...),
    category: FeeCategory = Form(...),
    session: Session = Depends(get_session),
):
    result = process_scan(session, token=token.strip(), category=category)
    status_code = status.HTTP_200_OK if result.ok else _STATUS_BY_KIND.get(
        result.kind, status.HTTP_400_BAD_REQUEST
    )
    return JSONResponse(
        {
            "ok": result.ok,
            "message": result.message,
            "person_name": result.person_name,
            "punctuality_status": result.punctuality_status.value if result.punctuality_status else None,
            "arrival_time": result.arrival_time.strftime("%H:%M:%S") if result.arrival_time else None,
        },
        status_code=status_code,
    )
