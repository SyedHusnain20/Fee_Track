"""FeeCycle generation and payment tracking — Section 3's "manage fee
payment history, mark cycles paid" and Section 5's snapshot-at-generation
billing model.

Per Key Design Principle #7, every FeeCycle change here — generation,
marking paid, marking unpaid — writes through the audit-log hook.

_current_period() uses school_today() (Asia/Karachi-aware), not naive
date.today() — see app/core/timezone.py. The server's system clock runs
in UTC, so naive date.today() could default this page to the wrong month
during the nightly UTC/Karachi day-rollover window.
"""

from datetime import datetime
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, or_, select
from weasyprint import HTML

from app.api.deps import get_current_admin
from app.api.students import CATEGORY_LABELS, DISCOUNT_TYPE_LABELS
from app.core.database import get_session
from app.core.timezone import school_today
from app.models.admin_user import AdminUser
from app.models.enums import AuditAction, FeeCycleStatus
from app.models.fee_cycle import FeeCycle
from app.models.student import Student
from app.services.audit import write_audit_log
from app.services.fee_cycle_generation import generate_fee_cycles
from app.services.notifications import create_fee_notification

router = APIRouter(prefix="/fee-cycles", tags=["fee-cycles"])
templates = Jinja2Templates(directory="app/templates")


def _current_period() -> str:
    today = school_today()
    return f"{today.year:04d}-{today.month:02d}"


def _snapshot(cycle: FeeCycle) -> dict:
    return {
        "student_id": cycle.student_id,
        "period": cycle.period,
        "total_due": float(cycle.total_due),
        "status": cycle.status.value,
        "paid_date": cycle.paid_date.isoformat() if cycle.paid_date else None,
        "collected_by_id": cycle.collected_by_id,
    }


def _safe_redirect(candidate: Optional[str], fallback: str) -> str:
    # Only ever follows a relative in-app path — the "next" field below is
    # always one we render ourselves (student detail vs fee-cycles list),
    # but this keeps it from ever becoming an open redirect if that changes.
    if candidate and candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return fallback


def _counts(cycles: list[FeeCycle]) -> dict:
    """Non-sensitive student counts for this page — the actual Rs amounts
    (revenue/collected/outstanding) moved to /settings, since fee totals
    are financial info that shouldn't be visible to every admin who opens
    this page. See app.api.settings for the amount-based version.
    """
    total_count = len(cycles)
    paid_count = sum(1 for c in cycles if c.status == FeeCycleStatus.PAID)
    remaining_count = total_count - paid_count
    return {
        "total_count": total_count,
        "paid_count": paid_count,
        "remaining_count": remaining_count,
    }


@router.get("", response_class=HTMLResponse)
async def list_fee_cycles(
    request: Request,
    period: Optional[str] = None,
    search: Optional[str] = None,
    message: Optional[str] = None,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    period = period or _current_period()
    search_term = search.strip() if search else ""

    query = (
        select(FeeCycle)
        .join(Student, FeeCycle.student_id == Student.id)
        .where(FeeCycle.period == period)
        # Ascending, not descending: FeeCycleStatus is a native Postgres
        # enum ordered by declaration (UNPAID, then PAID — see
        # app/models/enums.py), so ascending puts unpaid rows first. This
        # was intentionally flipped from the original descending order,
        # which surfaced already-handled paid rows above the ones that
        # still need attention.
        .order_by(FeeCycle.status.asc(), FeeCycle.student_id)
    )
    if search_term:
        like = f"%{search_term}%"
        query = query.where(or_(Student.name.ilike(like), Student.roll_number.ilike(like)))

    cycles = session.exec(query).all()

    return templates.TemplateResponse(
        "fee_cycles/list.html",
        {
            "request": request,
            "admin": admin,
            "period": period,
            "search": search_term,
            "cycles": cycles,
            "message": message,
            **_counts(cycles),
        },
    )


def _invoice_context(session: Session, cycle_id: int) -> dict:
    """Shared lookups + template context for both the on-screen preview
    and the PDF export, so the two can never drift apart into showing
    different numbers for the same cycle."""
    cycle = session.get(FeeCycle, cycle_id)
    if not cycle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fee cycle not found.")
    if cycle.status != FeeCycleStatus.PAID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An invoice is only available for a fee cycle that's marked paid.",
        )

    student = session.get(Student, cycle.student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")

    # No ORM relationship on FeeCycle.collected_by_id (see the model) —
    # looked up manually here, the one place that actually needs the name.
    collected_by = session.get(AdminUser, cycle.collected_by_id) if cycle.collected_by_id else None

    return {
        "cycle": cycle,
        "student": student,
        "collected_by": collected_by,
        # category_breakdown's keys are plain strings (FeeCategory.value,
        # from the JSON snapshot) — string-keyed here too so the
        # template can look labels up directly without an enum
        # round-trip. category_order fixes iteration to School,
        # Coaching, English, Computer regardless of dict insertion
        # order, so the breakdown reads the same way every time.
        "category_labels": {c.value: label for c, label in CATEGORY_LABELS.items()},
        "category_order": [c.value for c in CATEGORY_LABELS],
        "discount_type_labels": {dt.value: label for dt, label in DISCOUNT_TYPE_LABELS.items()},
        # Derived from the cycle's own id -- unique for free, no new
        # counter/table needed, matches this table's existing
        # snapshot-not-recompute philosophy (Section 5).
        "invoice_number": f"INV-{cycle.id:06d}",
    }


@router.get("/{cycle_id}/invoice", response_class=HTMLResponse)
async def view_invoice(
    cycle_id: int,
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    context = _invoice_context(session, cycle_id)
    return templates.TemplateResponse(
        "fee_cycles/invoice.html",
        {"request": request, **context},
    )


@router.get("/{cycle_id}/invoice/print", response_class=HTMLResponse)
async def print_invoice_thermal(
    cycle_id: int,
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    """80mm thermal-receipt layout for the bill printer — a separate
    document from the A4 PDF invoice, not the same content resized. The
    main invoice preview opens this in a popup (window.open, not a plain
    link) so it's allowed to auto-trigger the OS print dialog on load
    and close itself once printing is done. Whichever printer the admin
    has selected/set as default in that dialog is what actually prints —
    this page has no direct USB/serial access to the bill printer, it
    just renders at the bill printer's own paper width so a normal
    browser print goes to it looking right.
    """
    context = _invoice_context(session, cycle_id)
    return templates.TemplateResponse(
        "fee_cycles/invoice_print.html",
        {"request": request, **context},
    )


@router.get("/{cycle_id}/invoice.pdf")
async def download_invoice_pdf(
    cycle_id: int,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    """Real, server-rendered PDF — not the browser's own Ctrl+P / "Print
    to PDF", which bakes in the browser's own date/URL header-footer and
    depends on whatever print settings the admin's browser happens to
    have. WeasyPrint renders the same markup the on-screen preview uses
    (see _invoice_document.html) straight to PDF bytes, so the output is
    identical regardless of who opens it or what browser they're on.
    """
    context = _invoice_context(session, cycle_id)
    fragment = templates.env.get_template("fee_cycles/_invoice_document.html").render(context)
    document_html = f"<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>{fragment}</body></html>"
    pdf_bytes = HTML(string=document_html).write_pdf()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{context["invoice_number"]}.pdf"'},
    )


@router.post("/generate")
async def generate(
    request: Request,
    period: str = Form(...),
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    try:
        result = generate_fee_cycles(session, period=period, admin_id=admin.id)
    except ValueError as exc:
        return templates.TemplateResponse(
            "fee_cycles/list.html",
            {
                "request": request,
                "admin": admin,
                "period": period,
                "search": "",
                "cycles": [],
                "message": str(exc),
                **_counts([]),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    session.commit()
    msg = (
        f"Generated {result['created']} fee cycle(s) for {period}. "
        f"Skipped {result['skipped_existing']} already generated, "
        f"{result['skipped_zero_due']} with no active enrollments."
    )
    return RedirectResponse(
        url=f"/fee-cycles?period={period}&message={quote(msg)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{cycle_id}/mark-paid")
async def mark_paid(
    cycle_id: int,
    next: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    cycle = session.get(FeeCycle, cycle_id)
    if not cycle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fee cycle not found.")

    if cycle.status != FeeCycleStatus.PAID:
        before = _snapshot(cycle)
        cycle.status = FeeCycleStatus.PAID
        cycle.paid_date = school_today()
        cycle.collected_by_id = admin.id
        cycle.updated_by_id = admin.id
        cycle.updated_at = datetime.utcnow()
        session.add(cycle)

        write_audit_log(
            session,
            admin_id=admin.id,
            action=AuditAction.UPDATE,
            entity_type="FeeCycle",
            entity_id=cycle.id,
            before_value=before,
            after_value=_snapshot(cycle),
        )

        # Surfaced to super admins via the navbar bell — see
        # app.services.notifications. Student is looked up here (no ORM
        # relationship traversal needed elsewhere on this path) same as
        # view_invoice() above does for the same cycle.student_id.
        student = session.get(Student, cycle.student_id)
        if student:
            create_fee_notification(session, cycle, student, admin)

        session.commit()

    # show_invoice tells the destination page (fee-cycles list or student
    # detail, whichever "next" points to) to auto-open the invoice in a
    # pop-up modal — see the <dialog> + inline script in those templates.
    fallback = f"/fee-cycles?period={cycle.period}"
    destination = _safe_redirect(next, fallback)
    separator = "&" if "?" in destination else "?"
    return RedirectResponse(
        url=f"{destination}{separator}show_invoice={cycle.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{cycle_id}/mark-unpaid")
async def mark_unpaid(
    cycle_id: int,
    next: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    cycle = session.get(FeeCycle, cycle_id)
    if not cycle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fee cycle not found.")

    if cycle.status != FeeCycleStatus.UNPAID:
        before = _snapshot(cycle)
        cycle.status = FeeCycleStatus.UNPAID
        cycle.paid_date = None
        # A cycle that isn't currently paid was never "collected" by
        # anyone in the present tense — see the field's docstring on
        # FeeCycle. The audit log entry just below still records who
        # flipped it back to unpaid, and before_value still shows who had
        # collected it before this change, so that history isn't lost.
        cycle.collected_by_id = None
        cycle.updated_by_id = admin.id
        cycle.updated_at = datetime.utcnow()
        session.add(cycle)

        write_audit_log(
            session,
            admin_id=admin.id,
            action=AuditAction.UPDATE,
            entity_type="FeeCycle",
            entity_id=cycle.id,
            before_value=before,
            after_value=_snapshot(cycle),
        )
        session.commit()

    fallback = f"/fee-cycles?period={cycle.period}"
    return RedirectResponse(
        url=_safe_redirect(next, fallback), status_code=status.HTTP_303_SEE_OTHER
    )
