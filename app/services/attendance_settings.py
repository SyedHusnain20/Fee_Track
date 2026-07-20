"""Reads/writes per-session attendance timing from SystemSetting.
Section 3: admin capability to "set category timings + grace periods",
updated for the School/Academy redesign — now scoped to AttendanceSession
(2 values) rather than FeeCategory (4 values). School has both a start
time and a grace period; Academy has a start time only (reference/
reporting purposes — there's no late calculation for Academy at all, so a
grace period is meaningless for it and no academy_grace_minutes key
exists).
"""
from datetime import time
from typing import Optional

from sqlmodel import Session

from app.models.enums import AttendanceSession
from app.models.system_setting import SystemSetting

DEFAULT_GRACE_MINUTES = 15  # Section 4's stated default


def _start_time_key(attendance_session: AttendanceSession) -> str:
    return f"{attendance_session.value}_start_time"


def _grace_minutes_key(attendance_session: AttendanceSession) -> str:
    return f"{attendance_session.value}_grace_minutes"


def get_session_start_time(session: Session, attendance_session: AttendanceSession) -> Optional[time]:
    row = session.get(SystemSetting, _start_time_key(attendance_session))
    if not row:
        return None
    hour_str, minute_str = row.value.split(":")
    return time(int(hour_str), int(minute_str))


def get_session_grace_minutes(session: Session, attendance_session: AttendanceSession) -> int:
    row = session.get(SystemSetting, _grace_minutes_key(attendance_session))
    return int(row.value) if row else DEFAULT_GRACE_MINUTES


def set_session_timing(
    session: Session,
    attendance_session: AttendanceSession,
    start_time: time,
    grace_minutes: Optional[int] = None,
) -> None:
    start_key = _start_time_key(attendance_session)
    start_row = session.get(SystemSetting, start_key)
    if start_row:
        start_row.value = start_time.strftime("%H:%M")
    else:
        start_row = SystemSetting(key=start_key, value=start_time.strftime("%H:%M"))
    session.add(start_row)

    # Academy has no grace_minutes concept — the settings route simply
    # doesn't pass one for Academy, and nothing gets written for that key.
    if grace_minutes is not None:
        grace_key = _grace_minutes_key(attendance_session)
        grace_row = session.get(SystemSetting, grace_key)
        if grace_row:
            grace_row.value = str(grace_minutes)
        else:
            grace_row = SystemSetting(key=grace_key, value=str(grace_minutes))
        session.add(grace_row)