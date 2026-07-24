"""Attendance scan processing — Step 9, updated for the School/Academy
redesign. Core logic behind the kiosk's POST /kiosk/scan endpoint: resolve
a scanned QR token to a Student or Teacher, and record an AttendanceRecord
against one of two kiosk sessions — School (on-time/late judgment against
a configured start time + grace period) or Academy (covers all of
Coaching/English/Computer under one daily scan, arrival time logged with
no punctuality judgment at all).

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

from sqlmodel import Session, select

from app.core.timezone import SCHOOL_TIMEZONE
from app.models.attendance_record import AttendanceRecord
from app.models.enums import AttendanceSession, PunctualityStatus
from app.models.student import Student
from app.models.teacher import Teacher
from app.services.attendance_settings import get_session_grace_minutes, get_session_start_time


@dataclass
class ScanResult:
    ok: bool
    message: str
    kind: Optional[str] = (
        None  # "unrecognized" | "inactive" | "duplicate" | "unconfigured", on failure
    )
    person_name: Optional[str] = None
    punctuality_status: Optional[PunctualityStatus] = None
    arrival_time: Optional[time] = None


def _compute_punctuality(arrival: time, start_time: time, grace_minutes: int) -> PunctualityStatus:
    anchor = date(2000, 1, 1)  # arbitrary — only the time-of-day arithmetic matters
    cutoff = (datetime.combine(anchor, start_time) + timedelta(minutes=grace_minutes)).time()
    return PunctualityStatus.ON_TIME if arrival <= cutoff else PunctualityStatus.LATE


def process_scan(session: Session, token: str, attendance_session: AttendanceSession) -> ScanResult:
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
        AttendanceRecord.session == attendance_session,
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
                f"{person.name} already scanned for {attendance_session.value} today "
                f"at {already_scanned.arrival_time.strftime('%H:%M')}."
            ),
        )

    punctuality_status: Optional[PunctualityStatus] = None

    if attendance_session == AttendanceSession.SCHOOL:
        start_time = get_session_start_time(session, attendance_session)
        if start_time is None:
            return ScanResult(
                ok=False,
                kind="unconfigured",
                message=( 
                    "No start time configured for School yet — "
                    "set it on the Settings page first."
                ),            
            )
        grace_minutes = get_session_grace_minutes(session, attendance_session)
        punctuality_status = _compute_punctuality(arrival_time, start_time, grace_minutes)
    # Academy: deliberately no punctuality judgment. Academy's own start
    # time, if configured, is reference/reporting-only — never read here,
    # never blocks a scan if unset.

    record = AttendanceRecord(
        student_id=person.id if person_type == "student" else None,
        teacher_id=person.id if person_type == "teacher" else None,
        scan_date=scan_date,
        arrival_time=arrival_time,
        session=attendance_session,
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
