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

Manual-attendance-entry feature, Phase 2: process_manual_entry() is the
fallback path for when the scanner itself is unavailable. Unlike
process_scan, it's only reachable from an authenticated route
(app/api/attendance_manual.py) — every record it creates is stamped
is_manual=True and marked_by_id=<the admin who entered it>, for
accountability that a kiosk scan doesn't have (and can't have, since the
kiosk has no login at all). Both functions converge on the same
_finalize_attendance() below once a person has been resolved, so the
inactive/duplicate/punctuality rules are identical either way — a manual
entry follows exactly the same attendance rules as a real scan, just with
a different, more forgiving way of identifying who it's for.

Manual ID matching (resolve_manual_identifier): teacher staff_id is
always exactly 4 digits, auto-numbered 0001-9999 (app/services/staff_id.py);
student roll_number is always exactly 5 characters, cohort-code + sequence
(app/services/roll_number.py). That fixed-width difference is enough to
tell the two apart from typed digits alone, no separate
"Student/Teacher" toggle needed:
  - 1-4 digits  -> teacher, zero-padded up to 4 (so "1", "23", "0023",
    "456" all resolve the same as typing the full "0023"/"0456" — gate
    staff shouldn't have to remember or type leading zeros for a teacher).
  - exactly 5 digits -> student, matched exactly as typed (roll numbers
    are printed in full on ID cards, so no padding leniency here).
  - anything else (non-digits, 6+ digits) -> not a valid identifier of
    either kind.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional, Union

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.timezone import SCHOOL_TIMEZONE
from app.models.attendance_record import AttendanceRecord
from app.models.enums import AttendanceSession, PunctualityStatus
from app.models.student import Student
from app.models.teacher import Teacher
from app.services.attendance_settings import get_session_grace_minutes, get_session_start_time

TEACHER_STAFF_ID_LENGTH = 4
STUDENT_ROLL_NUMBER_LENGTH = 5


@dataclass
class ScanResult:
    ok: bool
    message: str
    kind: Optional[str] = (
        None  # "unrecognized" | "inactive" | "duplicate" | "unconfigured", on failure
    )
    person_name: Optional[str] = None
    person_type: Optional[str] = None  # "student" | "teacher", once resolved
    punctuality_status: Optional[PunctualityStatus] = None
    arrival_time: Optional[time] = None


def _compute_punctuality(arrival: time, start_time: time, grace_minutes: int) -> PunctualityStatus:
    anchor = date(2000, 1, 1)  # arbitrary — only the time-of-day arithmetic matters
    cutoff = (datetime.combine(anchor, start_time) + timedelta(minutes=grace_minutes)).time()
    return PunctualityStatus.ON_TIME if arrival <= cutoff else PunctualityStatus.LATE


def resolve_manual_identifier(
    session: Session, identifier: str
) -> tuple[Optional[Union[Student, Teacher]], Optional[str]]:
    """Resolve a manually-typed identifier to (person, person_type), or
    (None, None) if it doesn't match the expected shape for either kind or
    doesn't match any record. See module docstring for the digit-length
    rule this implements."""
    cleaned = identifier.strip()
    if not cleaned.isdigit():
        return None, None

    if len(cleaned) <= TEACHER_STAFF_ID_LENGTH:
        padded = cleaned.zfill(TEACHER_STAFF_ID_LENGTH)
        person = session.exec(select(Teacher).where(Teacher.staff_id == padded)).first()
        return person, "teacher"

    if len(cleaned) == STUDENT_ROLL_NUMBER_LENGTH:
        person = session.exec(select(Student).where(Student.roll_number == cleaned)).first()
        return person, "student"

    # 6+ digits — not a valid identifier of either kind.
    return None, None


def _finalize_attendance(
    session: Session,
    person: Union[Student, Teacher],
    person_type: str,
    attendance_session: AttendanceSession,
    *,
    is_manual: bool,
    marked_by_id: Optional[int],
) -> ScanResult:
    """Shared by process_scan and process_manual_entry once a person has
    already been resolved — inactive check, duplicate-scan check,
    punctuality calc, and record creation are identical either way."""
    if not person.is_active:
        return ScanResult(
            ok=False,
            kind="inactive",
            message=f"{person.name} is not an active {person_type}.",
            person_type=person_type,
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
            person_type=person_type,
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
                person_type=person_type,
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
        is_manual=is_manual,
        marked_by_id=marked_by_id,
    )
    session.add(record)
    try:
        # Flush now (not just commit) so the partial unique index — one
        # scan per (student-or-teacher, session, day) — surfaces here as
        # a catchable IntegrityError. The already_scanned check above
        # closes the common case, but two near-simultaneous scans for the
        # same person (a double-tap, a kiosk retrying a flaky request)
        # can both pass that check before either commits; without this,
        # the loser's commit raises straight through process_scan/
        # process_manual_entry as an unhandled 500 at the kiosk instead
        # of the same friendly duplicate message the normal case gets.
        # Same race, same fix as app/api/enrollments.py's create_enrollment.
        session.flush()
    except IntegrityError:
        session.rollback()
        winner = session.exec(existing_query).first()
        arrival = winner.arrival_time.strftime("%H:%M") if winner else arrival_time.strftime("%H:%M")
        return ScanResult(
            ok=False,
            kind="duplicate",
            message=f"{person.name} already scanned for {attendance_session.value} today at {arrival}.",
            person_type=person_type,
        )

    session.commit()

    return ScanResult(
        ok=True,
        message="Scan recorded." if not is_manual else "Attendance recorded manually.",
        person_name=person.name,
        person_type=person_type,
        punctuality_status=punctuality_status,
        arrival_time=arrival_time,
    )


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

    return _finalize_attendance(
        session, person, person_type, attendance_session, is_manual=False, marked_by_id=None
    )


def process_manual_entry(
    session: Session,
    identifier: str,
    attendance_session: AttendanceSession,
    marked_by_id: int,
) -> ScanResult:
    person, person_type = resolve_manual_identifier(session, identifier)

    if person is None:
        return ScanResult(
            ok=False,
            kind="unrecognized",
            message="No teacher or student found with that ID.",
        )

    return _finalize_attendance(
        session,
        person,
        person_type,
        attendance_session,
        is_manual=True,
        marked_by_id=marked_by_id,
    )