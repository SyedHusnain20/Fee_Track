"""Reusable audit-log write helper.

Key Design Principle (Section 13 of the spec): every admin-initiated change
to Enrollment or FeeCycle must write through this hook — not optional.
Built now as shared infra so Phase 2/3's Enrollment and FeeCycle routes can
just call write_audit_log(...) rather than each hand-rolling it.
"""

from typing import Any, Optional

from sqlmodel import Session

from app.models.audit_log import AuditLog
from app.models.enums import AuditAction


def write_audit_log(
    session: Session,
    *,
    admin_id: int,
    action: AuditAction,
    entity_type: str,
    entity_id: int,
    before_value: Optional[dict[str, Any]] = None,
    after_value: Optional[dict[str, Any]] = None,
) -> None:
    session.add(
        AuditLog(
            admin_id=admin_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_value=before_value,
            after_value=after_value,
        )
    )
    # Deliberately no session.commit() here — the caller's own commit
    # (which also saves the Enrollment/FeeCycle/etc. change) covers this
    # row too, so the audit entry and the change it describes land in the
    # same transaction and can never drift out of sync.
