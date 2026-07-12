"""One-off CLI to bootstrap the very first super-admin account.

There's no public registration route by design (Section 3 of the spec:
accounts are provisioned only by a super-admin). Run this once against a
fresh database to create account #1, then log in and create the other two
through the POST /admin/accounts route.

Usage (inside the running api container, matching the sys.path pattern
already used by scripts/backup_to_b2.py):
    docker compose exec api python scripts/create_super_admin.py
"""
import sys
from pathlib import Path
from getpass import getpass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select

from app.core.database import engine
from app.core.security import hash_password
from app.models.admin_user import AdminUser


def main():
    name = input("Full name: ").strip()
    email = input("Email: ").strip().lower()
    password = getpass("Password: ")
    confirm = getpass("Confirm password: ")

    if not name or not email:
        print("Name and email are required. Aborting.")
        return

    if password != confirm:
        print("Passwords don't match. Aborting.")
        return

    if len(password) < 8:
        print("Password should be at least 8 characters. Aborting.")
        return

    with Session(engine) as session:
        existing = session.exec(select(AdminUser).where(AdminUser.email == email)).first()
        if existing:
            print(f"An admin with email {email} already exists. Aborting.")
            return

        admin = AdminUser(
            name=name,
            email=email,
            password_hash=hash_password(password),
            is_active=True,
            is_super_admin=True,
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        print(f"Super-admin created: {email} (id={admin.id})")


if __name__ == "__main__":
    main()
