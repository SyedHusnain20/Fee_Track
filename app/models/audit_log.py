from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Column, ForeignKey, Integer
from sqlmodel import Field, SQLModel

from app.models._enum_utils import str_enum_type
from app.models.enums import AuditAction


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    # Nullable + ON DELETE SET NULL: a pending AdminUser's own self-signup
    # CREATE entry references itself as the actor (see auth.signup_submit),
    # and admin_accounts.reject_admin later hard-deletes that same
    # AdminUser row. Without SET NULL, Postgres's default RESTRICT blocks
    # that delete with a FK violation, which is exactly what caused reject
    # to 500 on literally every request. before_value/after_value already
    # snapshot the actor's name/email at write time, so nulling admin_id
    # here loses no forensic information, only the live FK link.
    admin_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("admin_user.id", ondelete="SET NULL"), index=True
        ),
    )
    action: AuditAction = Field(sa_column=Column(str_enum_type(AuditAction), nullable=False))
    entity_type: str = Field(max_length=100, index=True)  # e.g. "Enrollment", "FeeCycle"
    entity_id: int = Field(index=True)
    before_value: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    after_value: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
