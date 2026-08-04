from datetime import date, time
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, Column, Index, text
from sqlmodel import Field, Relationship, SQLModel

from app.models._enum_utils import str_enum_type
from app.models.enums import AttendanceSession, PunctualityStatus

if TYPE_CHECKING:
    from app.models.student import Student
    from app.models.teacher import Teacher


class AttendanceRecord(SQLModel, table=True):
    __tablename__ = "attendance_record"
    __table_args__ = (
        CheckConstraint(
            "(student_id IS NOT NULL AND teacher_id IS NULL) OR "
            "(student_id IS NULL AND teacher_id IS NOT NULL)",
            name="ck_attendance_exactly_one_owner",
        ),
        # One scan per (person, day, session) — session replaces the old
        # 4-value category as of the School/Academy redesign. Two partial
        # indexes, not one combined UNIQUE(...): Postgres treats NULLs as
        # distinct from each other in unique indexes, so a single
        # constraint wouldn't stop two teacher rows (student_id always
        # NULL for those) from colliding.
        Index(
            "ix_attendance_one_scan_per_student_session_day",
            "student_id",
            "scan_date",
            "session",
            unique=True,
            postgresql_where=text("student_id IS NOT NULL"),
        ),
        Index(
            "ix_attendance_one_scan_per_teacher_session_day",
            "teacher_id",
            "scan_date",
            "session",
            unique=True,
            postgresql_where=text("teacher_id IS NOT NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: Optional[int] = Field(default=None, foreign_key="student.id", index=True)
    teacher_id: Optional[int] = Field(default=None, foreign_key="teacher.id", index=True)
    scan_date: date = Field(index=True)
    arrival_time: time
    # No FK to category_fee_default anymore — AttendanceSession's "academy"
    # value has no corresponding row there. FeeCategory's coaching/english/
    # computer values still do (billing is untouched), but attendance and
    # billing are deliberately decoupled as of this redesign.
    session: AttendanceSession = Field(
        sa_column=Column(str_enum_type(AttendanceSession), nullable=False, index=True)
    )
    # Nullable as of the School/Academy redesign: Academy scans log
    # arrival time only, with no on-time/late judgment. NULL here means
    # "not tracked for this session type," not "unknown."
    punctuality_status: Optional[PunctualityStatus] = Field(
        default=None, sa_column=Column(str_enum_type(PunctualityStatus), nullable=True)
    )

    # Manual-attendance-entry feature, Phase 1. False/NULL for every scan
    # made through the (deliberately unauthenticated) kiosk — that flow is
    # untouched. True only for a record created via the new authenticated
    # /attendance/manual fallback, used when the scanner itself is down.
    # marked_by_id is NULL for real kiosk scans (there's no admin identity
    # to attach — the kiosk has no login) and always set for a manual
    # entry, since that path requires being logged in; this is the
    # accountability trail a scan doesn't need and can't have. No ORM
    # Relationship() here, matching created_by_id/collected_by_id on
    # FeeCycle — this codebase looks these up manually where the admin's
    # name is actually needed rather than eager-loading a relationship for
    # every AttendanceRecord query.
    is_manual: bool = Field(default=False)
    marked_by_id: Optional[int] = Field(
        default=None, foreign_key="admin_user.id", index=True
    )

    student: Optional["Student"] = Relationship(back_populates="attendance_records")
    teacher: Optional["Teacher"] = Relationship(back_populates="attendance_records")