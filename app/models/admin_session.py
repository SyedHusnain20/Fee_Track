"""AdminSession — server-side session store for admin login.

Added in Step 6, on top of the 11 tables finalized in Section 8 of the
project spec. A DB-backed session (rather than a stateless signed cookie)
was a deliberate choice: it lets a super-admin's "deactivate admin" action
kill that admin's session immediately, and it leaves room for a "log out
everywhere" feature later without a redesign.

Registered against your real admin_user table and following your existing
snake_case __tablename__ / naive-UTC-datetime conventions (see admin_user.py,
audit_log.py).
"""

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class AdminSession(SQLModel, table=True):
    __tablename__ = "admin_session"

    token: str = Field(primary_key=True, max_length=64)
    admin_id: int = Field(foreign_key="admin_user.id", index=True, nullable=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime = Field(nullable=False, index=True)
    last_seen_at: Optional[datetime] = Field(default=None)
    user_agent: Optional[str] = Field(default=None, max_length=255)
