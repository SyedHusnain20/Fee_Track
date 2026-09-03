"""Fee-payment notifications for the super-admin navbar bell.

One row per successful payment transaction (see
app/api/fee_cycles.py's record_payment_route(), which calls
create_fee_notification() right after committing the payment) —
surfaced only to super admins, never to regular admins.

student_name, fee_amount, and collected_by_name are snapshotted at
creation time rather than re-derived later, per the rationale already
recorded on the Notification model itself and matching FeeCycle's own
category_breakdown/total_due snapshot pattern: a later student rename or
admin-user change must never rewrite what a past notification said
happened.

No scheduler/cron exists anywhere in this app, so retention is enforced
opportunistically — every new notification prunes anything past
NOTIFICATION_RETENTION_DAYS, rather than relying on a timer that doesn't
exist (same rationale as Holiday's mark-only design and
attendance_archive's on-demand archiving).
"""

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from app.models.admin_user import AdminUser
from app.models.notification import Notification
from app.models.student import Student

NOTIFICATION_RETENTION_DAYS = 30
RECENT_NOTIFICATIONS_LIMIT = 20


def _prune_old(session: Session) -> None:
    """Delete anything older than the retention window. Called from
    create_fee_notification() on every write — see module docstring for
    why this happens here instead of on a schedule."""
    cutoff = datetime.utcnow() - timedelta(days=NOTIFICATION_RETENTION_DAYS)
    stale = session.exec(select(Notification).where(Notification.created_at < cutoff)).all()
    for row in stale:
        session.delete(row)


def create_fee_notification(
    session: Session,
    student: Student,
    fee_amount,
    admin: AdminUser,
) -> Notification:
    """Snapshot a just-collected fee as a notification row. Caller is
    expected to commit afterward — this only adds to the session and
    flushes, same convention as app.services.holidays.mark_holiday.

    fee_amount is passed explicitly (rather than read off a FeeCycle)
    since a due-carry-forward payment (see app.services.fee_payments) can
    settle several cycles in one transaction — the amount worth notifying
    on is the actual payment amount, not any single cycle's total_due.
    """
    notification = Notification(
        student_id=student.id,
        student_name=student.name,
        fee_amount=fee_amount,
        collected_by_id=admin.id,
        collected_by_name=admin.name,
    )
    session.add(notification)
    _prune_old(session)
    session.flush()
    return notification


def list_recent(session: Session, limit: int = RECENT_NOTIFICATIONS_LIMIT) -> list[Notification]:
    return session.exec(
        select(Notification).order_by(Notification.created_at.desc()).limit(limit)
    ).all()


def unread_count(session: Session) -> int:
    return session.exec(
        select(func.count())
        .select_from(Notification)
        .where(Notification.is_read == False)  # noqa: E712
    ).one()


def mark_all_read(session: Session) -> None:
    """Called when the super admin opens the notification dropdown —
    clears the unread badge. Rows are updated individually (not a bulk
    UPDATE) so this stays inside the caller's existing Session/commit
    boundary, matching every other write in this codebase."""
    unread = session.exec(
        select(Notification).where(Notification.is_read == False)  # noqa: E712
    ).all()
    for row in unread:
        row.is_read = True
        session.add(row)
