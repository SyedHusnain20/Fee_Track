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
from decimal import Decimal
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.api.deps import get_current_admin
from app.core.database import get_session
from app.core.timezone import school_today
from app.models.admin_user import AdminUser
from app.models.enums import AuditAction, FeeCycleStatus
from app.models.fee_cycle import FeeCycle
from app.models.student import Student
from app.services.audit import write_audit_log
from app.services.fee_cycle_generation import generate_fee_cycles

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
    }


def _safe_redirect(candidate: Optional[str], fallback: str) -> str:
    # Only ever follows a relative in-app path — the "next" field below is
    # always one we render ourselves (student detail vs fee-cycles list),
    # but this keeps it from ever becoming an open redirect if that changes.
    if candidate and candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return fallback


def _totals(cycles: list[FeeCycle]) -> dict:
    """Three distinct figures, not two that happen to collapse together
    when everything's paid:
      - total_revenue: every cycle for the period, paid or not (what was billed)
      - total_collected: paid cycles only (what's actually in hand)
      - total_outstanding: unpaid cycles only (what's still owed)
    total_revenue == total_collected + total_outstanding, always.
    """
    total_revenue = sum((c.total_due for c in cycles), Decimal("0.00"))
    total_collected = sum(
        (c.total_due for c in cycles if c.status == FeeCycleStatus.PAID), Decimal("0.00")
    )
    total_outstanding = sum(
        (c.total_due for c in cycles if c.status == FeeCycleStatus.UNPAID), Decimal("0.00")
    )
    return {
        "total_revenue": total_revenue,
        "total_collected": total_collected,
        "total_outstanding": total_outstanding,
    }


@router.get("", response_class=HTMLResponse)
async def list_fee_cycles(
    request: Request,
    period: Optional[str] = None,
    message: Optional[str] = None,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    period = period or _current_period()
    cycles = session.exec(
        select(FeeCycle)
        .where(FeeCycle.period == period)
        .order_by(FeeCycle.status.desc(), FeeCycle.student_id)
    ).all()

    return templates.TemplateResponse(
        "fee_cycles/list.html",
        {
            "request": request,
            "admin": admin,
            "period": period,
            "cycles": cycles,
            "message": message,
            **_totals(cycles),
        },
    )


@router.get("/{cycle_id}/invoice", response_class=HTMLResponse)
async def view_invoice(
    cycle_id: int,
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
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

    return templates.TemplateResponse(
        "fee_cycles/invoice.html",
        {
            "request": request,
            "cycle": cycle,
            "student": student,
            # Derived from the cycle's own id -- unique for free, no new
            # counter/table needed, matches this table's existing
            # snapshot-not-recompute philosophy (Section 5).
            "invoice_number": f"INV-{cycle.id:06d}",
        },
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
                "cycles": [],
                "message": str(exc),
                **_totals([]),
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
    return RedirectResponse(url=_safe_redirect(next, fallback), status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse(url=_safe_redirect(next, fallback), status_code=status.HTTP_303_SEE_OTHER)
