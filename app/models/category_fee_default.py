from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, Column, Index
from sqlmodel import Field, SQLModel

from app.models._enum_utils import str_enum_type
from app.models.enums import FeeCategory


class CategoryFeeDefault(SQLModel, table=True):
    """One row per (category, class-level band). category is no longer
    unique alone -- School has 4 bands, Coaching has 5, English and
    Computer are each a single flat band covering every class level
    (min_class_offset=0, max_class_offset=14). No longer an FK target for
    Enrollment.category -- see the migration docstring for why.
    """
    __tablename__ = "category_fee_default"
    __table_args__ = (
        CheckConstraint("min_class_offset <= max_class_offset", name="ck_category_fee_band_range"),
        Index("ix_category_fee_default_category_band", "category", "min_class_offset", unique=True),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    category: FeeCategory = Field(sa_column=Column(str_enum_type(FeeCategory), nullable=False, index=True))
    band_name: str = Field(max_length=50)
    min_class_offset: int = Field(ge=0, le=14)
    max_class_offset: int = Field(ge=0, le=14)
    default_amount: Decimal = Field(max_digits=10, decimal_places=2)