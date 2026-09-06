"""Super-admin-only routes for creating/deactivating other AdminUser
accounts. Step 6.

list_admins/create_admin/deactivate_admin return JSON, matching the "no
dedicated frontend step" model from Section 10 of the spec.

Phase 4 of the approval-workflow feature adds the HTML back-office piece
for the self-signup flow (Phase 2/3): a GET /admin/accounts/requests page
listing every not-yet-approved AdminUser, plus POST .../approve and
POST .../reject actions. These are separate from the JSON routes above
because they're form-posted from a Jinja2 page and redirect back to it,
rather than returning JSON for a future JS frontend.

Phase 5 adds an audit-log entry to both approve_admin and reject_admin,
recording the acting super admin — the counterpart to auth.signup_submit's
own audit-log write for the initial request.

Also logs create_admin/deactivate_admin now (an earlier gap — every other
AdminUser mutation in this file was already audited) and enforces the
same 8-character minimum password length /signup does, so creating an
account directly isn't a way to bypass that policy.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.api.deps import require_super_admin
from app.core.database import get_session
from app.core.security import hash_password
from app.models.admin_session import AdminSession
from app.models.admin_user import AdminUser
from app.models.enums import AuditAction
from app.services.audit import write_audit_log

router = APIRouter(prefix="/admin/accounts", tags=["admin-accounts"])
templates = Jinja2Templates(directory="app/templates")


@router.get("")
async def list_admins(
    session: Session = Depends(get_session),
    _: AdminUser = Depends(require_super_admin),
):
    admins = session.exec(select(AdminUser)).all()
    return [
        {
            "id": a.id,
            "name": a.name,
            "email": a.email,
            "is_active": a.is_active,
            "is_super_admin": a.is_super_admin,
        }
        for a in admins
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_admin(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    is_super_admin: bool = Form(False),
    session: Session = Depends(get_session),
    current: AdminUser = Depends(require_super_admin),
):
    email = email.strip().lower()
    existing = session.exec(select(AdminUser).where(AdminUser.email == email)).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use.")

    # Same minimum enforced on /signup (app/api/auth.py) -- a super admin
    # creating an account directly shouldn't be a way to bypass the
    # password policy self-service signup enforces.
    if len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters.",
        )

    admin = AdminUser(
        name=name,
        email=email,
        password_hash=hash_password(password),
        is_active=True,
        is_super_admin=is_super_admin,
    )
    session.add(admin)
    # Flush (not just commit) so admin.id exists for the audit-log write
    # below — same pattern as app.api.enrollments's create route.
    session.flush()

    write_audit_log(
        session,
        admin_id=current.id,
        action=AuditAction.CREATE,
        entity_type="AdminUser",
        entity_id=admin.id,
        before_value=None,
        after_value={
            "name": admin.name,
            "email": admin.email,
            "is_super_admin": admin.is_super_admin,
        },
    )
    session.commit()
    session.refresh(admin)
    return {"id": admin.id, "email": admin.email, "is_super_admin": admin.is_super_admin}


@router.post("/{admin_id}/deactivate")
async def deactivate_admin(
    admin_id: int,
    session: Session = Depends(get_session),
    current: AdminUser = Depends(require_super_admin),
):
    if admin_id == current.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can't deactivate your own account.",
        )

    target = session.get(AdminUser, admin_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found.")

    before_active = target.is_active
    target.is_active = False
    session.add(target)

    # Kill every live session belonging to this admin immediately, rather
    # than letting them ride out until natural expiry.
    live_sessions = session.exec(
        select(AdminSession).where(AdminSession.admin_id == admin_id)
    ).all()
    for s in live_sessions:
        session.delete(s)

    write_audit_log(
        session,
        admin_id=current.id,
        action=AuditAction.UPDATE,
        entity_type="AdminUser",
        entity_id=target.id,
        before_value={"is_active": before_active},
        after_value={"is_active": target.is_active},
    )
    session.commit()
    return {"id": target.id, "is_active": target.is_active}


@router.get("/requests", response_class=HTMLResponse)
async def list_admin_requests(
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(require_super_admin),
):
    pending = session.exec(
        select(AdminUser).where(AdminUser.is_approved == False)  # noqa: E712
    ).all()
    return templates.TemplateResponse(
        "settings/admin_requests.html",
        {"request": request, "admin": admin, "pending": pending},
    )


@router.post("/{admin_id}/approve")
async def approve_admin(
    admin_id: int,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(require_super_admin),
):
    target = session.get(AdminUser, admin_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found.")

    if target.is_approved:
        # Nothing to do — already approved (e.g. a double-submitted form).
        return RedirectResponse(
            url="/admin/accounts/requests", status_code=status.HTTP_303_SEE_OTHER
        )

    target.is_approved = True
    session.add(target)

    write_audit_log(
        session,
        admin_id=admin.id,
        action=AuditAction.UPDATE,
        entity_type="AdminUser",
        entity_id=target.id,
        before_value={"is_approved": False},
        after_value={"is_approved": True},
    )
    session.commit()

    return RedirectResponse(url="/admin/accounts/requests", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{admin_id}/reject")
async def reject_admin(
    admin_id: int,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(require_super_admin),
):
    target = session.get(AdminUser, admin_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found.")

    # Reject only applies to a still-pending request. An already-approved
    # admin is a real, in-use account by this point — removing that access
    # is the separate "deactivate" action above, not a reject.
    if target.is_approved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This admin is already approved; use deactivate instead.",
        )

    # Per product decision, rejection is a hard delete rather than a status
    # flip — a rejected email is immediately free to submit a new /signup
    # request. Pending admins can never have a live session (login_submit
    # blocks it before a session is issued), but the sweep below is kept
    # for defense-in-depth / consistency with deactivate_admin above.
    live_sessions = session.exec(
        select(AdminSession).where(AdminSession.admin_id == admin_id)
    ).all()
    for s in live_sessions:
        session.delete(s)

    # Captured before the delete below — target.id is still readable on
    # the Python object at that point, but there's no reason to rely on
    # that once a plain int will do. entity_id on AuditLog has no foreign
    # key (see audit_log.py), so logging a reference to a row that's about
    # to be gone in the same transaction is fine.
    deleted_id = target.id
    write_audit_log(
        session,
        admin_id=admin.id,
        action=AuditAction.DELETE,
        entity_type="AdminUser",
        entity_id=deleted_id,
        before_value={"name": target.name, "email": target.email, "is_approved": False},
        after_value=None,
    )
    session.delete(target)
    session.commit()

    return RedirectResponse(url="/admin/accounts/requests", status_code=status.HTTP_303_SEE_OTHER)  