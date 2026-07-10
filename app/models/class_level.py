from typing import TYPE_CHECKING, List, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.student import Student


class ClassLevel(SQLModel, table=True):
    __tablename__ = "class_level"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=50)
    class_offset: int = Field(unique=True, index=True, ge=0, le=14)

    students: List["Student"] = Relationship(back_populates="class_level")
