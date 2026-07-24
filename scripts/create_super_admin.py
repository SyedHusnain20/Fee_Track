"""One-off script to create a super admin account — needed after a local
dev DB wipe (schema exists via `alembic upgrade head`, but no admin row
exists to log in with). Not part of seed_reference_data.py on purpose:
credentials shouldn't be created by a script that's safe to blindly re-run
in every environment.

Usage:
    docker compose exec api python scripts/create_super_admin.py
"""

import sys
from getpass import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from argon2 import PasswordHasher
from sqlmodel import Session, select

from app.core.database import engine
from app.models.admin_user import AdminUser

ph = PasswordHasher()


def main() -> None:
    name = input("Full name: ").strip()
    email = input("Email: ").strip().lower()
    password = getpass("Password: ")
    confirm = getpass("Confirm password: ")

    if password != confirm:
        print("Passwords don't match — aborting.")
        return
    if len(password) < 8:
        print("Password too short (min 8 chars) — aborting.")
        return

    with Session(engine) as session:
        existing = session.exec(select(AdminUser).where(AdminUser.email == email)).first()
        if existing:
            print(f"An AdminUser with email {email} already exists (id={existing.id}) — aborting.")
            return

        admin = AdminUser(
            name=name,
            email=email,
            password_hash=ph.hash(password),
            is_active=True,
            is_super_admin=True,
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)

    print(f"Super admin created: id={admin.id}, email={admin.email}")


if __name__ == "__main__":
    main()
