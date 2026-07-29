"""Fee due-day setting — the day of the month after which an unpaid
student's fee is flagged overdue on /students. Stored in SystemSetting,
same key-value pattern as app/services/attendance_settings.py, under a
single "fee_due_day" key.

Defaults to 10, matching the value that was previously hardcoded in
app/api/students.py (`today.day > 10`) before this became admin-configurable.
"""

from sqlmodel import Session

from app.models.system_setting import SystemSetting

DEFAULT_FEE_DUE_DAY = 10
_FEE_DUE_DAY_KEY = "fee_due_day"


def get_fee_due_day(session: Session) -> int:
    row = session.get(SystemSetting, _FEE_DUE_DAY_KEY)
    return int(row.value) if row else DEFAULT_FEE_DUE_DAY


def set_fee_due_day(session: Session, day: int) -> None:
    row = session.get(SystemSetting, _FEE_DUE_DAY_KEY)
    if row:
        row.value = str(day)
    else:
        row = SystemSetting(key=_FEE_DUE_DAY_KEY, value=str(day))
    session.add(row)
