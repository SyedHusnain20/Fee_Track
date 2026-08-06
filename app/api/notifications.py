"""Fee-payment notification bell — read/list/mark-read endpoints backing
the navbar dropdown in base.html. Super-admin only, matching
app.services.notifications' access rationale: this surfaces who collected
what fee and when, not something every admin should see.

JSON endpoints, not template-rendered pages: the bell is a small dropdown
fragment that needs to appear on every page in the app, not a page of its
own. Injecting notification context into every one of this codebase's
existing routes would mean touching dozens of unrelated files; a plain
fetch() from base.html's inline script against these two endpoints is
simpler and keeps the bell fully decoupled from whatever page it's
floating on top of.
"""

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.api.deps import require_super_admin
from app.core.database import get_session
from app.models.admin_user import AdminUser
from app.models.student import Student
from app.services.notifications import list_recent, mark_all_read, unread_count

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/recent")
async def recent_notifications(
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(require_super_admin),
):
    items = list_recent(session)

    # roll_number is looked up fresh rather than snapshotted on the
    # Notification row (unlike student_name/fee_amount/collected_by_name)
    # because it's the same permanent ID-card number used everywhere else
    # in this codebase (reports, id_cards, kiosk) -- it never changes for
    # a given student, so there's nothing to protect against re-deriving.
    student_ids = {n.student_id for n in items}
    roll_numbers = {}
    if student_ids:
        roll_numbers = {
            s.id: s.roll_number
            for s in session.exec(select(Student).where(Student.id.in_(student_ids))).all()
        }

    return {
        "unread_count": unread_count(session),
        "items": [
            {
                "id": n.id,
                "student_id": n.student_id,
                "roll_number": roll_numbers.get(n.student_id, "—"),
                "student_name": n.student_name,
                "fee_amount": str(n.fee_amount),
                "collected_by_name": n.collected_by_name,
                "created_at": n.created_at.isoformat(),
            }
            for n in items
        ],
    }


@router.post("/mark-read")
async def mark_read(
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(require_super_admin),
):
    mark_all_read(session)
    session.commit()
    return {"ok": True}
