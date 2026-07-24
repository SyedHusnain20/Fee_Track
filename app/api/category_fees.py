"""Category default fee management — updated for class-level-banded fees.
Admin edits each band's fee amount; band structure itself (which
class-offset ranges exist per category) is fixed by the migration that
created it -- adding/removing bands needs a new migration, this route
only edits amounts.
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


def _grouped_defaults(session: Session) -> list[dict]:
    rows = session.exec(
        select(CategoryFeeDefault).order_by(
            CategoryFeeDefault.category, CategoryFeeDefault.min_class_offset
        )
    ).all()
    groups: dict[FeeCategory, list[CategoryFeeDefault]] = {c: [] for c in FeeCategory}
    for row in rows:
        groups[row.category].append(row)
    return [{"category": c, "label": CATEGORY_LABELS[c], "bands": groups[c]} for c in FeeCategory]


@router.get("", response_class=HTMLResponse)
async def list_category_fees(
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    return templates.TemplateResponse(
        "category_fees/list.html",
        {"request": request, "admin": admin, "groups": _grouped_defaults(session), "error": None},
    )


@router.post("/{band_id}")
async def update_category_fee(
    band_id: int,
    request: Request,
    default_amount: str = Form(...),
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    row = session.get(CategoryFeeDefault, band_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fee band not found.")

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
                "groups": _grouped_defaults(session),
                "error": "Enter a valid, non-negative amount.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    row.default_amount = amount
    session.add(row)
    session.commit()
    return RedirectResponse(url="/category-fees", status_code=status.HTTP_303_SEE_OTHER)
