from enum import Enum
from typing import Type

from sqlalchemy import Enum as SAEnum


def str_enum_type(enum_cls: Type[Enum], **kwargs) -> SAEnum:
    """
    By default, SQLAlchemy's Enum type stores/compares Python Enum members by
    their .name (e.g. 'ACTIVE'), not their .value (e.g. 'active'). Our enums
    are (str, Enum) subclasses whose lowercase .value IS the string we
    actually want stored — matching the spec, matching raw SQL/reporting
    expectations, and matching what any non-Python consumer would expect.
    values_callable forces SQLAlchemy to use .value instead of .name.
    """
    return SAEnum(enum_cls, values_callable=lambda x: [e.value for e in x], **kwargs)
