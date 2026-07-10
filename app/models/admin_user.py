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
    created_at: datetime = Field(default_factory=datetime.utcnow)
