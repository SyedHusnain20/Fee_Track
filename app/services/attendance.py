"""Attendance scan processing — Step 9. Core logic behind the kiosk's
POST /kiosk/scan endpoint: resolve a scanned QR token to a Student or
Teacher, compute on-time/late against the currently-selected category's
configured start time + grace period, and write the AttendanceRecord.

Deliberately not authenticated and deliberately minimal in what it returns
— per spec, "the attendance kiosk is not a role... cannot read back any
data." The name + status returned to the kiosk UI is the one exception:
without it, gate staff have no way to catch a scan going to the wrong
person (mixed-up QR codes, a shared/borrowed ID), which would defeat
attendance tracking's purpose entirely. That's not general read access —
there's no search, no listing, nothing beyond an echo of the scan just made.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional, Union
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.models.attendance_record import AttendanceRecord
from app.models.enums import FeeCategory, PunctualityStatus
from app.models.student import Student
from app.models.teacher import Teacher
from app.services.attendance_settings import get_category_grace_minutes, get_category_start_time

# Hardcoded rather than trusting the server process's local time zone —
# python:3.12-slim doesn't ship IANA tzdata by default, so datetime.now()
# without an explicit zone risks silently running in UTC (Pakistan is
# UTC+5), which would make every scan's on-time/late calculation wrong by
# 5 hours. See requirements.txt note re: the `tzdata` package.
SCHOOL_TIMEZONE = ZoneInfo("Asia/Karachi")


@dataclass
class ScanResult:
    ok: bool
    message: str
    kind: Optional[str] = None  # "unrecognized" | "inactive" | "duplicate" | "unconfigured", on failure
    person_name: Optional[str] = None
    punctuality_status: Optional[PunctualityStatus] = None
    arrival_time: Optional[time] = None


def _compute_punctuality(arrival: time, start_time: time, grace_minutes: int) -> PunctualityStatus:
    anchor = date(2000, 1, 1)  # arbitrary — only the time-of-day arithmetic matters
    cutoff = (datetime.combine(anchor, start_time) + timedelta(minutes=grace_minutes)).time()
    return PunctualityStatus.ON_TIME if arrival <= cutoff else PunctualityStatus.LATE


def process_scan(session: Session, token: str, category: FeeCategory) -> ScanResult:
    person: Optional[Union[Student, Teacher]] = session.exec(
        select(Student).where(Student.qr_code == token)
    ).first()
    person_type = "student"
    if person is None:
        person = session.exec(select(Teacher).where(Teacher.qr_code == token)).first()
        person_type = "teacher"

    if person is None:
        return ScanResult(ok=False, kind="unrecognized", message="Unrecognized QR code.")

    if not person.is_active:
        return ScanResult(
            ok=False, kind="inactive", message=f"{person.name} is not an active {person_type}."
        )

    now = datetime.now(SCHOOL_TIMEZONE)
    scan_date = now.date()
    arrival_time = now.time().replace(microsecond=0)

    existing_query = select(AttendanceRecord).where(
        AttendanceRecord.scan_date == scan_date,
        AttendanceRecord.category == category,
    )
    existing_query = existing_query.where(
        AttendanceRecord.student_id == person.id
        if person_type == "student"
        else AttendanceRecord.teacher_id == person.id
    )

    already_scanned = session.exec(existing_query).first()
    if already_scanned:
        return ScanResult(
            ok=False,
            kind="duplicate",
            message=(
                f"{person.name} already scanned for {category.value} today "
                f"at {already_scanned.arrival_time.strftime('%H:%M')}."
            ),
        )

    start_time = get_category_start_time(session, category)
    if start_time is None:
        return ScanResult(
            ok=False,
            kind="unconfigured",
            message=f"No start time configured for {category.value} yet — set it on the Settings page first.",
        )
    grace_minutes = get_category_grace_minutes(session, category)
    punctuality_status = _compute_punctuality(arrival_time, start_time, grace_minutes)

    record = AttendanceRecord(
        student_id=person.id if person_type == "student" else None,
        teacher_id=person.id if person_type == "teacher" else None,
        scan_date=scan_date,
        arrival_time=arrival_time,
        category=category,
        punctuality_status=punctuality_status,
    )
    session.add(record)
    session.commit()

    return ScanResult(
        ok=True,
        message="Scan recorded.",
        person_name=person.name,
        punctuality_status=punctuality_status,
        arrival_time=arrival_time,
    )
