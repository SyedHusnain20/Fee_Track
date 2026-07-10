from datetime import date, time
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, Column
from sqlmodel import Field, Relationship, SQLModel

from app.models._enum_utils import str_enum_type
from app.models.enums import PunctualityStatus

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
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: Optional[int] = Field(default=None, foreign_key="student.id", index=True)
    teacher_id: Optional[int] = Field(default=None, foreign_key="teacher.id", index=True)
    scan_date: date = Field(index=True)
    arrival_time: time
    punctuality_status: PunctualityStatus = Field(
        sa_column=Column(str_enum_type(PunctualityStatus), nullable=False)
    )

    student: Optional["Student"] = Relationship(back_populates="attendance_records")
    teacher: Optional["Teacher"] = Relationship(back_populates="attendance_records")
