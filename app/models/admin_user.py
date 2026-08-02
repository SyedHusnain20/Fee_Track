from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class AdminUser(SQLModel, table=True):
    __tablename__ = "admin_user"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=150)
    email: str = Field(unique=True, index=True, max_length=255)
    password_hash: str
    is_active: bool = Field(default=True)
    is_super_admin: bool = Field(default=False)  # only super-admin can manage other AdminUsers
    # False for a freshly self-registered admin awaiting super-admin sign-off
    # (Phase 2's public /signup route). Login is blocked until a super admin
    # approves the request from Admin Requests (Phase 4); rejection deletes
    # the row outright rather than flipping this back to False, so
    # is_approved never needs to represent "rejected" as a state.
    # Admins created directly by a super admin via admin_accounts.py, and
    # every pre-existing row as of this migration, default to True.
    is_approved: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)