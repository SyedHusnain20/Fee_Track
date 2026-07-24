"""Central timezone handling — the school operates in Pakistan (UTC+5),
but the server/container's system clock runs in UTC. Any "what calendar
day is it" business logic (attendance, fee cycles, dashboards, reports)
must use SCHOOL_TIMEZONE-aware dates, never naive date.today() or
datetime.utcnow().date() — those silently disagree with the kiosk's own
scan_date during the roughly 5-hour daily window where Karachi has
already rolled over to a new calendar day but UTC hasn't yet (Karachi
midnight = 19:00 UTC the previous day).

Naive datetime.utcnow() remains correct and UNCHANGED for anything that
is NOT calendar-day-sensitive — audit log timestamps, created_at/
updated_at columns, session expiry. Those intentionally stay naive UTC
per the existing convention (see security.py's new_expiry() docstring) —
this module doesn't change that, it only fixes "what day is today" for
business logic that was incorrectly using the naive form.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

SCHOOL_TIMEZONE = ZoneInfo("Asia/Karachi")


def school_today() -> date:
    """The current calendar date in the school's local timezone. Use this
    anywhere "today" means a business/attendance/fee calendar day —
    never date.today() or datetime.utcnow().date()."""
    return datetime.now(SCHOOL_TIMEZONE).date()
