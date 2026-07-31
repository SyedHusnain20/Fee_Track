from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Column
from sqlmodel import Field, Relationship, SQLModel

from app.models._enum_utils import str_enum_type
from app.models.enums import Qualification

if TYPE_CHECKING:
    from app.models.attendance_record import AttendanceRecord

# Note: 'salary' below is the teacher's base monthly salary, used as
# total_salary in the attendance-based monthly deduction formula (see
# app.services.teacher_salary, added in Phase 3):
#   net_salary = salary - (salary / 30) * absent_days
# Nullable in the DB (see migration) so existing teacher rows created
# before this field existed don't break -- but the create/edit form
# (app/api/teachers.py) requires it going forward.


class Teacher(SQLModel, table=True):
    __tablename__ = "teacher"

    id: Optional[int] = Field(default=None, primary_key=True)
    staff_id: str = Field(max_length=20, unique=True, index=True)
    name: str = Field(max_length=150)

    # Added in Phase 1 (profile expansion). All nullable in the DB for
    # backward compatibility with teacher rows created before this
    # migration -- the form makes them required for new/edited teachers.
    father_name: Optional[str] = Field(default=None, max_length=150)
    contact: Optional[str] = Field(default=None, max_length=20)
    # Fixed dropdown (intermediate/graduate/masters/phd) rather than free
    # text, so profile data and future reporting stay consistent. Native
    # enum column, nullable in the DB for the same backward-compatibility
    # reason as the rest of this block.
    qualification: Optional[Qualification] = Field(
        default=None, sa_column=Column(str_enum_type(Qualification), nullable=True)
    )
    designation: Optional[str] = Field(default=None, max_length=100)
    salary: Optional[Decimal] = Field(default=None, max_digits=10, decimal_places=2)
    # When the teacher actually started. Nullable for the same
    # backward-compatibility reason as the rest of this block, but with a
    # real behavioral consequence when it's missing: app.services.
    # teacher_salary can't tell a pre-existing teacher's join date apart
    # from "unknown," so it falls back to counting from the 1st of the
    # month for anyone without one set. For every teacher created going
    # forward, the form requires it, specifically so a teacher hired
    # mid-month doesn't get counted absent for days before they joined.
    date_joined: Optional[date] = Field(default=None)

    # Which subjects/categories this teacher teaches. Deliberately four
    # plain booleans rather than a link to FeeCategory: a teacher can
    # teach more than one, and there's no per-teacher fee amount here --
    # this is a profile/reporting attribute only, unrelated to what a
    # student is billed. Values line up with FeeCategory's four values
    # (school/coaching/english/computer) per user's confirmation, even
    # though the field name here is teaches_english to match that enum
    # rather than the "language" wording used when the feature was
    # requested.
    teaches_school: bool = Field(default=False)
    teaches_coaching: bool = Field(default=False)
    teaches_english: bool = Field(default=False)
    teaches_computer: bool = Field(default=False)

    qr_code: str = Field(unique=True, index=True)
    is_active: bool = Field(default=True)

    attendance_records: List["AttendanceRecord"] = Relationship(back_populates="teacher")