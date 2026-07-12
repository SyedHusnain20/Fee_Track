# Step 7, Phase 1 — Students, Teachers, Dashboard

Phase 1 of "enrollment & fee module (+ bulk of the admin UI)." Enrollment,
discounts, and fee cycles are Phases 2 and 3 — not in this drop.

## Two scope decisions made before writing any code (see chat for full reasoning)
1. **Roll-number/QR-token generation moved from Step 8 into now.** Your
   `Student` table already has `roll_number`/`qr_code` as `NOT NULL UNIQUE`
   (Step 5's migration) — a Student can't be inserted without them. Only the
   Section 6 *algorithm* moved earlier; rendering an actual scannable QR
   *image* (the `qrcode` library) is still Step 8's job.
2. **Reference data was never seeded.** `ClassLevel` (15 rows) and
   `CategoryFeeDefault` (4 rows) exist as empty tables — first student
   creation would have hit a foreign-key violation without this.

## Files, and where they go
```
app/services/__init__.py           → app/services/__init__.py        (new folder)
app/services/roll_number.py        → app/services/roll_number.py
app/services/qr_token.py           → app/services/qr_token.py
app/services/audit.py              → app/services/audit.py
app/api/students.py                → app/api/students.py
app/api/teachers.py                → app/api/teachers.py
app/api/dashboard.py               → app/api/dashboard.py
app/templates/base.html            → app/templates/base.html
app/templates/dashboard.html       → app/templates/dashboard.html
app/templates/students/list.html   → app/templates/students/list.html   (new folder)
app/templates/students/form.html   → app/templates/students/form.html
app/templates/teachers/list.html   → app/templates/teachers/list.html   (new folder)
app/templates/teachers/form.html   → app/templates/teachers/form.html
scripts/seed_reference_data.py     → scripts/seed_reference_data.py
```

## One manual edit: `app/main.py`

Add three more router imports/includes alongside the two from Step 6:
```python
from app.api.auth import router as auth_router
from app.api.admin_accounts import router as admin_accounts_router
from app.api.dashboard import router as dashboard_router
from app.api.students import router as students_router
from app.api.teachers import router as teachers_router

app.include_router(auth_router)
app.include_router(admin_accounts_router)
app.include_router(dashboard_router)
app.include_router(students_router)
app.include_router(teachers_router)
```

## Then, in order

```bash
# 1. these are all Python files under app/ and scripts/ — both are bind-mounted,
#    so a container restart picks them up without a rebuild
docker compose up -d

# 2. seed the reference data (idempotent — safe to re-run)
docker compose exec api python scripts/seed_reference_data.py

# 3. no new tables this phase, so no alembic migration needed — verify:
docker compose exec api alembic heads
# should still print: 8f3d1a9b6c22 (head)
```

No migration step this time — Phase 1 only adds application code and seed
*data*, not schema.

## Verifying it works
1. Log in at `/login` (your Step 6 super-admin). You should land on `/dashboard`
   for real now, instead of the 404 you'd have gotten before this phase —
   showing "0 active students" / "0 active teachers."
2. `/teachers` → **+ Add teacher** → fill in a staff ID + name → should
   appear in the list with an auto-generated QR token (not shown in the UI
   yet — that's Step 8's display work) and Active status.
3. `/students` → **+ Add student** → pick a class, leave admission year at
   its default → should get a roll number back. Sanity-check against
   Section 6's formula: a fresh Class 1 admission in 2026 has offset 3, so
   cohort code = `(2026 - 3) mod 100` = `23`, and the first student in that
   cohort gets sequence `001` → roll number `23001`. This matches the
   spec's own worked examples (Class 12 in 2026 → `12xxx`, Foundation 1 in
   2026 → `26xxx`) using the same formula.
4. Add a second Class 1 student the same year — sequence should increment
   to `002` with the same cohort code as student 1.
5. Deactivate a student or teacher from the list — status badge should flip
   to "Inactive," dashboard counts should drop by one.
6. `ruff check .` and `pytest -v` still green.

## What's still missing (Phases 2 and 3, not this drop)
- Enrolling a student into categories, with discounts.
- Editing the 4 `CategoryFeeDefault` amounts.
- Generating/marking `FeeCycle` rows paid.
- Wiring `write_audit_log()` (already built, in `app/services/audit.py`)
  into the Enrollment and FeeCycle routes — Key Design Principle #7 says
  this is mandatory for those two entities specifically, so it's held until
  those routes exist rather than applied to Student/Teacher, which the spec
  doesn't require it for.

Say "Phase 2" (or "continue") when you're ready and I'll build Enrollment +
discounts next.
