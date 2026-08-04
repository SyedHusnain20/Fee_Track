from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Holiday(SQLModel, table=True):
    """One row per calendar day the school is closed, beyond the standing
    Sunday-off rule that's baked directly into the "academic day"/"working
    day" logic elsewhere (app/api/reports.py, app/services/teacher_salary.py).
    Existence of a row for a date IS the holiday marker — no separate
    active/inactive flag, since a holiday that's been un-marked should just
    not have a row at all (per product decision: the initial version of
    this feature is mark-only, no undo UI, so in practice rows are never
    removed once written — but the schema doesn't forbid it either).

    holiday_date, not `date`, to avoid shadowing the `date` type import —
    same convention as AttendanceRecord.scan_date.
    """

    __tablename__ = "holiday"

    id: Optional[int] = Field(default=None, primary_key=True)
    holiday_date: date = Field(unique=True, index=True)
    # Optional short label (e.g. "Eid", "Flood closure") for context on
    # reports later — not required, since the button this ships with
    # (Phase 5) is a single-click "mark today," no reason field on it yet.
    reason: Optional[str] = Field(default=None, max_length=255)
    # No ORM Relationship() to AdminUser, matching the rest of this
    # codebase's admin-FK convention (see AttendanceRecord.marked_by_id /
    # FeeCycle.created_by_id) — looked up manually where needed.
    marked_by_id: Optional[int] = Field(default=None, foreign_key="admin_user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)