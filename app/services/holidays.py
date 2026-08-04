"""Mark-a-day-as-holiday logic backing app/api/settings.py.

Per the product decision already recorded on the Holiday model itself:
this is mark-only, no undo UI. holiday_date is unique, so double-marking
the same date is a conflict rather than a silent no-op or a second row —
the caller (the settings route) turns that into a user-facing error
instead of a 500 from the DB's unique constraint.
"""

from datetime import date
from typing import Optional

from sqlmodel import Session, select

from app.models.holiday import Holiday

RECENT_HOLIDAYS_LIMIT = 10


def list_recent_holidays(session: Session, limit: int = RECENT_HOLIDAYS_LIMIT) -> list[Holiday]:
    return session.exec(
        select(Holiday).order_by(Holiday.holiday_date.desc()).limit(limit)
    ).all()


def mark_holiday(
    session: Session,
    holiday_date: date,
    reason: Optional[str],
    marked_by_id: int,
) -> Holiday:
    """Raises ValueError if holiday_date is already marked — checked
    up front rather than relying on the DB's unique constraint, so the
    route can show a clean validation message instead of a raw
    IntegrityError."""
    existing = session.exec(
        select(Holiday).where(Holiday.holiday_date == holiday_date)
    ).first()
    if existing:
        raise ValueError(f"{holiday_date.isoformat()} is already marked as a holiday.")

    holiday = Holiday(
        holiday_date=holiday_date,
        reason=reason.strip() if reason and reason.strip() else None,
        marked_by_id=marked_by_id,
    )
    session.add(holiday)
    session.flush()
    return holiday
