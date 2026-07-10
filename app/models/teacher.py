from typing import TYPE_CHECKING, List, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.attendance_record import AttendanceRecord


class Teacher(SQLModel, table=True):
    __tablename__ = "teacher"

    id: Optional[int] = Field(default=None, primary_key=True)
    staff_id: str = Field(max_length=20, unique=True, index=True)
    name: str = Field(max_length=150)
    qr_code: str = Field(unique=True, index=True)
    is_active: bool = Field(default=True)

    attendance_records: List["AttendanceRecord"] = Relationship(back_populates="teacher")
