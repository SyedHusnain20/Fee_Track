"""Pre-delivery reset — wipes every table that could hold test/demo data,
while deliberately leaving real school configuration untouched:
ClassLevel, CategoryFeeDefault, and SystemSetting are never touched here —
those are the client's actual reference data (classes, fee bands,
attendance timing), not test data, even if you set them up yourself while
building.

Wiped, in FK-safe order (children before parents):
  Notification, AttendanceRecord, FeeCycle, Enrollment, Student, Teacher,
  Holiday, AuditLog, AdminSession, RollNumberCounter (rows removed
  entirely, not just reset to 0 -- a fresh cohort recreates the row on
  first admission).

AdminUser is handled separately and only on explicit confirmation, since
deleting the wrong admin account is the one mistake here that can lock
you out. You're prompted for which admin email(s) to KEEP; everything
else is deleted. Answering with nothing skips AdminUser entirely, leaving
every admin account as-is.

Interactive by design, same pattern as seed_bulk_dummy_data.py -- prints
exactly what it's about to do and requires typing WIPE to proceed. Nothing
is deleted until that confirmation.

Usage:
    docker compose exec api python scripts/reset_for_delivery.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, delete, func, select

from app.core.database import engine
from app.models.admin_session import AdminSession
from app.models.admin_user import AdminUser
from app.models.attendance_record import AttendanceRecord
from app.models.audit_log import AuditLog
from app.models.enrollment import Enrollment
from app.models.fee_cycle import FeeCycle
from app.models.holiday import Holiday
from app.models.notification import Notification
from app.models.roll_number_counter import RollNumberCounter
from app.models.student import Student
from app.models.teacher import Teacher

# Order matters: children before parents, to satisfy FK constraints.
WIPE_MODELS = [
    Notification,
    AttendanceRecord,
    FeeCycle,
    Enrollment,
    Student,
    Teacher,
    Holiday,
    AuditLog,
    AdminSession,
    RollNumberCounter,
]

PRESERVED = ["ClassLevel", "CategoryFeeDefault", "SystemSetting"]


def main() -> None:
    with Session(engine) as session:
        print("This will permanently delete all rows from:")
        for model in WIPE_MODELS:
            count = session.exec(select(func.count()).select_from(model)).one()
            print(f"  {model.__tablename__}: {count} row(s)")
        print(f"\nNOT touched (real school config, kept as-is): {', '.join(PRESERVED)}")

        admins = session.exec(select(AdminUser)).all()
        print(f"\nAdminUser: {len(admins)} account(s) currently exist:")
        for a in admins:
            print(f"  id={a.id}  {a.email}  ({'super admin' if a.is_super_admin else 'admin'})")
        keep_input = input(
            "\nEmail(s) of admin account(s) to KEEP, comma-separated "
            "(leave blank to skip touching AdminUser entirely): "
        ).strip()
        keep_emails = {e.strip().lower() for e in keep_input.split(",") if e.strip()}

        if keep_emails:
            unknown = keep_emails - {a.email.lower() for a in admins}
            if unknown:
                print(f"These email(s) don't match any existing admin, aborting: {unknown}")
                return
            to_delete_admins = [a for a in admins if a.email.lower() not in keep_emails]
            print(f"\nWill ALSO delete {len(to_delete_admins)} admin account(s):")
            for a in to_delete_admins:
                print(f"  {a.email}")
        else:
            to_delete_admins = []
            print("\nAdminUser will be left untouched.")

        confirm = input("\nType WIPE to proceed, anything else to cancel: ").strip()
        if confirm != "WIPE":
            print("Cancelled — nothing was deleted.")
            return

        for model in WIPE_MODELS:
            session.exec(delete(model))

        for admin in to_delete_admins:
            # AdminSession rows for this admin are already gone (wiped
            # above, before AdminUser), so no FK conflict deleting these.
            session.delete(admin)

        session.commit()
        print("\nDone. Reference config (ClassLevel/CategoryFeeDefault/SystemSetting) is intact.")


if __name__ == "__main__":
    main()
