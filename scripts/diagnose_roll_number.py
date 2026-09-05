"""One-off diagnostic for the "roll number cohort code doesn't match
classmates" bug (e.g. a Foundation 3 student getting a 26xxx roll number
while other Foundation 3 students have 24xxx).

Roll numbers are generated once, at student creation, by
app/services/roll_number.py:

    cohort_code = (enrollment_year - class_level.class_offset) % 100

For two students in the SAME class, created in the SAME calendar year,
this always produces the SAME cohort_code -- class_offset is fixed per
class (Foundation 1/2/3 -> 0/1/2, Class 1-12 -> 3-14), so the only way two
"Foundation 3" students can land in different cohorts is if:

  (a) they were actually enrolled in different years (enrollment_year
      isn't stored anywhere after creation -- it's baked into the roll
      number and gone -- so this script can't rule it in or out directly,
      only by elimination against (b)); or
  (b) they don't actually share the same class_offset -- i.e. there are
      two different ClassLevel rows both named "Foundation 3" (or one
      student is quietly linked to a different row than the others), each
      with a different class_offset. class_offset has a UNIQUE constraint,
      so this can only happen via two rows with the SAME name but
      DIFFERENT offsets -- never two rows at the same offset.

This script prints every ClassLevel row and flags any name used by more
than one, then prints the specific student's own class_level_id/offset so
you can see directly which case you're in.

Usage:
    docker compose exec api python scripts/diagnose_roll_number.py <roll_number>
    docker compose exec api python scripts/diagnose_roll_number.py 26036
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select

from app.core.database import engine
from app.models.class_level import ClassLevel
from app.models.roll_number_counter import RollNumberCounter
from app.models.student import Student


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/diagnose_roll_number.py <roll_number>")
        sys.exit(1)
    target_roll_number = sys.argv[1]

    with Session(engine) as session:
        print("=== ClassLevel rows ===")
        levels = session.exec(select(ClassLevel).order_by(ClassLevel.class_offset)).all()
        by_name = defaultdict(list)
        for cl in levels:
            by_name[cl.name].append(cl)
            print(f"  id={cl.id:<4} name={cl.name!r:<18} class_offset={cl.class_offset}")

        duplicates = {name: rows for name, rows in by_name.items() if len(rows) > 1}
        if duplicates:
            print("\n!!! DUPLICATE CLASS NAMES (same name, different offsets) !!!")
            for name, rows in duplicates.items():
                offsets = ", ".join(f"id={r.id} offset={r.class_offset}" for r in rows)
                print(f"  {name!r}: {offsets}")
        else:
            print("\nNo duplicate class names found -- every name maps to exactly one offset.")

        print(f"\n=== Student with roll_number={target_roll_number!r} ===")
        student = session.exec(
            select(Student).where(Student.roll_number == target_roll_number)
        ).first()
        if not student:
            print("  No student found with that roll number.")
            return

        class_level = session.get(ClassLevel, student.class_level_id)
        print(f"  name: {student.name}")
        print(f"  class_level_id: {student.class_level_id}")
        print(f"  resolved class_level: name={class_level.name!r} class_offset={class_level.class_offset}" if class_level else "  resolved class_level: MISSING (dangling FK!)")

        cohort_code = target_roll_number[:2]
        print(f"\n  Roll number's cohort_code is {cohort_code!r}.")
        if class_level:
            implied_year = 2000 + int(cohort_code) + class_level.class_offset
            print(
                f"  Given this student's actual class_offset ({class_level.class_offset}), "
                f"that cohort_code implies enrollment_year was entered as {implied_year} "
                f"(or {implied_year - 100} if you expect a year before 2000)."
            )

        print("\n=== roll_number_counter rows ===")
        counters = session.exec(select(RollNumberCounter)).all()
        for c in counters:
            print(f"  cohort_code={c.cohort_code!r} last_sequence={c.last_sequence}")


if __name__ == "__main__":
    main()
