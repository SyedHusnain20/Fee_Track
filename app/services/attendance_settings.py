"""Reads/writes per-category attendance timing from SystemSetting.
Section 3: admin capability to "set category timings + grace periods". Key
naming follows the convention already in SystemSetting's own docstring
(school_start_time, coaching_grace_minutes, etc.) — one "<category>_start_
time" and one "<category>_grace_minutes" key per FeeCategory, seeded with
placeholder defaults by scripts/seed_reference_data.py.
"""
from datetime import time
from typing import Optional

from sqlmodel import Session

from app.models.enums import FeeCategory
from app.models.system_setting import SystemSetting

DEFAULT_GRACE_MINUTES = 15  # Section 4's stated default


def _start_time_key(category: FeeCategory) -> str:
    return f"{category.value}_start_time"


def _grace_minutes_key(category: FeeCategory) -> str:
    return f"{category.value}_grace_minutes"


def get_category_start_time(session: Session, category: FeeCategory) -> Optional[time]:
    row = session.get(SystemSetting, _start_time_key(category))
    if not row:
        return None
    hour_str, minute_str = row.value.split(":")
    return time(int(hour_str), int(minute_str))


def get_category_grace_minutes(session: Session, category: FeeCategory) -> int:
    row = session.get(SystemSetting, _grace_minutes_key(category))
    return int(row.value) if row else DEFAULT_GRACE_MINUTES


def set_category_timing(
    session: Session, category: FeeCategory, start_time: time, grace_minutes: int
) -> None:
    start_key = _start_time_key(category)
    start_row = session.get(SystemSetting, start_key)
    if start_row:
        start_row.value = start_time.strftime("%H:%M")
    else:
        start_row = SystemSetting(key=start_key, value=start_time.strftime("%H:%M"))
    session.add(start_row)

    grace_key = _grace_minutes_key(category)
    grace_row = session.get(SystemSetting, grace_key)
    if grace_row:
        grace_row.value = str(grace_minutes)
    else:
        grace_row = SystemSetting(key=grace_key, value=str(grace_minutes))
    session.add(grace_row)
