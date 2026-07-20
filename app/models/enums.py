from enum import Enum


class FeeCategory(str, Enum):
    SCHOOL = "school"
    COACHING = "coaching"
    ENGLISH = "english"
    COMPUTER = "computer"


class AttendanceSession(str, Enum):
    """Kiosk-side session grouping — separate from FeeCategory, which still
    drives billing with its 4 values unchanged. School has late/on-time
    tracking; Academy covers all of Coaching/English/Computer under one
    scan with no punctuality judgment at all."""
    SCHOOL = "school"
    ACADEMY = "academy"


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