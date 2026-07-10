from typing import TYPE_CHECKING, List, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.attendance_record import AttendanceRecord
    from app.models.class_level import ClassLevel
    from app.models.enrollment import Enrollment
    from app.models.fee_cycle import FeeCycle


class Student(SQLModel, table=True):
    __tablename__ = "student"

    id: Optional[int] = Field(default=None, primary_key=True)
    roll_number: str = Field(max_length=5, unique=True, index=True)
    name: str = Field(max_length=150)
    father_name: str = Field(max_length=150)
    parent_whatsapp: str = Field(max_length=20)
    qr_code: str = Field(unique=True, index=True)
    class_level_id: int = Field(foreign_key="class_level.id", index=True)
    is_active: bool = Field(default=True)

    class_level: "ClassLevel" = Relationship(back_populates="students")
    enrollments: List["Enrollment"] = Relationship(back_populates="student")
    fee_cycles: List["FeeCycle"] = Relationship(back_populates="student")
    attendance_records: List["AttendanceRecord"] = Relationship(back_populates="student")
