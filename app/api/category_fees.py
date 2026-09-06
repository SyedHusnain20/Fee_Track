"""Category default fee management — updated for class-level-banded fees.
Admin edits each band's fee amount; band structure itself (which
class-offset ranges exist per category) is fixed by the migration that
created it -- adding/removing bands needs a new migration, this route
only edits amounts.

The whole page is one form with one Save button (not a per-band form/
button) — the admin can edit any number of bands across any number of
categories and submit them all in a single POST. Only bands whose
submitted amount actually differs from what's stored get written; the
rest are left untouched (see update_category_fees below).

Restricted to require_super_admin — only reachable via /settings, and
only visible in the navbar to super admins, per explicit access-control
decision (same treatment as /settings and /rollover).

Per Key Design Principle #7, every changed band amount writes through the
audit-log hook (an earlier gap here — every other financial-setting
change in this app, e.g. category_fees's sibling settings.py, already
logged).
"""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.api.deps import require_super_admin
from app.core.database import get_session
from app.models.admin_user import AdminUser
from app.models.category_fee_default import CategoryFeeDefault
from app.models.enums import AuditAction, FeeCategory
from app.services.audit import write_audit_log

router = APIRouter(prefix="/category-fees", tags=["category-fees"])
templates = Jinja2Templates(directory="app/templates")

CATEGORY_LABELS = {
    FeeCategory.SCHOOL: "School",
    FeeCategory.COACHING: "Coaching",
    FeeCategory.ENGLISH: "Language",
    FeeCategory.COMPUTER: "Computer Courses",
    FeeCategory.OTHERS: "Others",
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
    admin: AdminUser = Depends(require_super_admin),
):
    return templates.TemplateResponse(
        "category_fees/list.html",
        {
            "request": request,
            "admin": admin,
            "groups": _grouped_defaults(session),
            "submitted": {},
            "field_errors": {},
            "error": None,
        },
    )


@router.post("")
async def update_category_fees(
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(require_super_admin),
):
    """Single endpoint for the whole page's single Save button. The form
    submits one amount_<band_id> field per band regardless of whether the
    admin touched it — we diff each against the stored value ourselves and
    only write the ones that actually changed, rather than trusting the
    client to tell us which fields were edited.
    """
    form = await request.form()
    rows = session.exec(select(CategoryFeeDefault)).all()

    submitted: dict[int, str] = {}
    field_errors: dict[int, str] = {}
    parsed: dict[int, Decimal] = {}

    for row in rows:
        raw = form.get(f"amount_{row.id}")
        if raw is None:
            continue  # field missing from the POST entirely — leave band alone
        submitted[row.id] = raw

        try:
            amount = Decimal(raw)
        except InvalidOperation:
            field_errors[row.id] = "Enter a valid amount."
            continue
        if amount < 0:
            field_errors[row.id] = "Amount can't be negative."
            continue
        parsed[row.id] = amount

    if field_errors:
        return templates.TemplateResponse(
            "category_fees/list.html",
            {
                "request": request,
                "admin": admin,
                "groups": _grouped_defaults(session),
                "submitted": submitted,
                "field_errors": field_errors,
                "error": "Fix the highlighted amount(s) below and save again.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    for row in rows:
        new_amount = parsed.get(row.id)
        if new_amount is not None and new_amount != row.default_amount:
            before = {"default_amount": float(row.default_amount)}
            row.default_amount = new_amount
            session.add(row)
            write_audit_log(
                session,
                admin_id=admin.id,
                action=AuditAction.UPDATE,
                entity_type="CategoryFeeDefault",
                entity_id=row.id,
                before_value=before,
                after_value={"default_amount": float(row.default_amount)},
            )

    session.commit()
    return RedirectResponse(url="/category-fees", status_code=status.HTTP_303_SEE_OTHER)
