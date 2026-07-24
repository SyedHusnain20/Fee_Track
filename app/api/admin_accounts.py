"""Super-admin-only routes for creating/deactivating other AdminUser
accounts. Step 6.

These return JSON for now (id/email pairs), matching the "no dedicated
frontend step" model from Section 10 of the spec — a proper HTML back-office
page for this can be layered on in Step 7 alongside the rest of the admin
UI, reusing these same routes.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, status
from sqlmodel import Session, select

from app.api.deps import require_super_admin
from app.core.database import get_session
from app.core.security import hash_password
from app.models.admin_session import AdminSession
from app.models.admin_user import AdminUser

router = APIRouter(prefix="/admin/accounts", tags=["admin-accounts"])


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
    _: AdminUser = Depends(require_super_admin),
):
    email = email.strip().lower()
    existing = session.exec(select(AdminUser).where(AdminUser.email == email)).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use.")

    admin = AdminUser(
        name=name,
        email=email,
        password_hash=hash_password(password),
        is_active=True,
        is_super_admin=is_super_admin,
    )
    session.add(admin)
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

    target.is_active = False
    session.add(target)

    # Kill every live session belonging to this admin immediately, rather
    # than letting them ride out until natural expiry.
    live_sessions = session.exec(
        select(AdminSession).where(AdminSession.admin_id == admin_id)
    ).all()
    for s in live_sessions:
        session.delete(s)

    session.commit()
    return {"id": target.id, "is_active": target.is_active}
