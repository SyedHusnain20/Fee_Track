"""Category default fee management — Section 3: admin capability to edit
the 4 global category default fees. A change here ripples live to every
enrolled student, since Enrollment never stores its own fee amount
(Section 5's compute_enrollment_fee always looks the current default up
live) — nothing else needs to be touched when a default changes.

Not wired into the audit-log hook: Key Design Principle #7 (Section 13)
scopes that requirement to Enrollment and FeeCycle specifically. Flagging
it here in case you'd rather have full coverage — it's a small addition
if so.
"""
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.api.deps import get_current_admin
from app.core.database import get_session
from app.models.admin_user import AdminUser
from app.models.category_fee_default import CategoryFeeDefault
from app.models.enums import FeeCategory

router = APIRouter(prefix="/category-fees", tags=["category-fees"])
templates = Jinja2Templates(directory="app/templates")

CATEGORY_LABELS = {
    FeeCategory.SCHOOL: "School",
    FeeCategory.COACHING: "Coaching",
    FeeCategory.ENGLISH: "English Language",
    FeeCategory.COMPUTER: "Computer Courses",
}


def _ordered_defaults(session: Session) -> list[CategoryFeeDefault]:
    rows = session.exec(select(CategoryFeeDefault)).all()
    order = {c: i for i, c in enumerate(FeeCategory)}
    return sorted(rows, key=lambda row: order[row.category])


@router.get("", response_class=HTMLResponse)
async def list_category_fees(
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    return templates.TemplateResponse(
        "category_fees/list.html",
        {
            "request": request,
            "admin": admin,
            "defaults": _ordered_defaults(session),
            "category_labels": CATEGORY_LABELS,
            "error": None,
        },
    )


@router.post("/{category}")
async def update_category_fee(
    category: FeeCategory,
    request: Request,
    default_amount: str = Form(...),
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    row = session.get(CategoryFeeDefault, category)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")

    amount = None
    try:
        amount = Decimal(default_amount)
    except InvalidOperation:
        pass

    if amount is None or amount < 0:
        return templates.TemplateResponse(
            "category_fees/list.html",
            {
                "request": request,
                "admin": admin,
                "defaults": _ordered_defaults(session),
                "category_labels": CATEGORY_LABELS,
                "error": "Enter a valid, non-negative amount.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    row.default_amount = amount
    session.add(row)
    session.commit()
    return RedirectResponse(url="/category-fees", status_code=status.HTTP_303_SEE_OTHER)
