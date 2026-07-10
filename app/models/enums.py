from enum import Enum


class FeeCategory(str, Enum):
    SCHOOL = "school"
    COACHING = "coaching"
    ENGLISH = "english"
    COMPUTER = "computer"


class DiscountType(str, Enum):
    NONE = "none"
    FIXED = "fixed"
    PERCENTAGE = "percentage"


class EnrollmentStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class FeeCycleStatus(str, Enum):
    UNPAID = "unpaid"
    PAID = "paid"


class PunctualityStatus(str, Enum):
    ON_TIME = "on_time"
    LATE = "late"


class AuditAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
