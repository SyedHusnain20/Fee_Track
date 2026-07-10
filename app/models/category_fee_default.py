from decimal import Decimal

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.models._enum_utils import str_enum_type
from app.models.enums import FeeCategory


class CategoryFeeDefault(SQLModel, table=True):
    __tablename__ = "category_fee_default"

    category: FeeCategory = Field(sa_column=Column(str_enum_type(FeeCategory), primary_key=True))
    default_amount: Decimal = Field(max_digits=10, decimal_places=2)
