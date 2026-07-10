from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.models._enum_utils import str_enum_type
from app.models.enums import AuditAction


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    admin_id: int = Field(foreign_key="admin_user.id", index=True)
    action: AuditAction = Field(sa_column=Column(str_enum_type(AuditAction), nullable=False))
    entity_type: str = Field(max_length=100, index=True)  # e.g. "Enrollment", "FeeCycle"
    entity_id: int = Field(index=True)
    before_value: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    after_value: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
