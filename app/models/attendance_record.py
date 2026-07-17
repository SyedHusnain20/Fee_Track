from datetime import date, time
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, text
from sqlmodel import Field, Relationship, SQLModel

from app.models._enum_utils import str_enum_type
from app.models.enums import FeeCategory, PunctualityStatus

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
        # One scan per (person, day, category) — added in Step 9 alongside
        # the category column itself. Two partial indexes, not one combined
        # UNIQUE(student_id, teacher_id, scan_date, category): Postgres
        # treats NULLs as distinct from each other in unique indexes, so a
        # single constraint wouldn't actually stop two teacher rows
        # (student_id is always NULL for those) from colliding. Mirrors the
        # pattern Enrollment already uses for its one-active-enrollment-
        # per-category constraint.
        Index(
            "ix_attendance_one_scan_per_student_category_day",
            "student_id", "scan_date", "category",
            unique=True,
            postgresql_where=text("student_id IS NOT NULL"),
        ),
        Index(
            "ix_attendance_one_scan_per_teacher_category_day",
            "teacher_id", "scan_date", "category",
            unique=True,
            postgresql_where=text("teacher_id IS NOT NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: Optional[int] = Field(default=None, foreign_key="student.id", index=True)
    teacher_id: Optional[int] = Field(default=None, foreign_key="teacher.id", index=True)
    scan_date: date = Field(index=True)
    arrival_time: time
    category: FeeCategory = Field(
        sa_column=Column(
            str_enum_type(FeeCategory),
            ForeignKey("category_fee_default.category"),
            nullable=False,
            index=True,
        )
    )
    punctuality_status: PunctualityStatus = Field(
        sa_column=Column(str_enum_type(PunctualityStatus), nullable=False)
    )

    student: Optional["Student"] = Relationship(back_populates="attendance_records")
    teacher: Optional["Teacher"] = Relationship(back_populates="attendance_records")
