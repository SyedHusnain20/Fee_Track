"""One-off seed script for fixed reference data: the 15 ClassLevel rows and
4 CategoryFeeDefault rows described in Sections 2, 5, and 6 of the spec.

Neither Step 5 nor Step 6 populated these — Student creation (Step 7) hard-
depends on ClassLevel existing via a foreign key, and Enrollment will depend
on CategoryFeeDefault the same way. Safe to re-run: skips rows that already
exist rather than erroring on the unique constraints.

Usage:
    docker compose exec api python scripts/seed_reference_data.py
"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select

from app.core.database import engine
from app.models.category_fee_default import CategoryFeeDefault
from app.models.class_level import ClassLevel
from app.models.enums import FeeCategory

# Section 6: Foundation 1-3 -> offsets 0-2, Class 1-12 -> offsets 3-14.
CLASS_LEVELS = [
    ("Foundation 1", 0),
    ("Foundation 2", 1),
    ("Foundation 3", 2),
] + [(f"Class {n}", n + 2) for n in range(1, 13)]

DEFAULT_FEE = Decimal("1000.00")  # Section 5: "starts at Rs 1,000, admin-editable"


def seed_class_levels(session: Session) -> None:
    existing = {cl.class_offset for cl in session.exec(select(ClassLevel)).all()}
    added = 0
    for name, offset in CLASS_LEVELS:
        if offset in existing:
            continue
        session.add(ClassLevel(name=name, class_offset=offset))
        added += 1
    print(f"ClassLevel: added {added}, skipped {len(CLASS_LEVELS) - added} already present")


def seed_category_fee_defaults(session: Session) -> None:
    existing = {c.category for c in session.exec(select(CategoryFeeDefault)).all()}
    added = 0
    for category in FeeCategory:
        if category in existing:
            continue
        session.add(CategoryFeeDefault(category=category, default_amount=DEFAULT_FEE))
        added += 1
    print(
        f"CategoryFeeDefault: added {added}, "
        f"skipped {len(list(FeeCategory)) - added} already present"
    )


def main() -> None:
    with Session(engine) as session:
        seed_class_levels(session)
        seed_category_fee_defaults(session)
        session.commit()
    print("Seed complete.")


if __name__ == "__main__":
    main()
