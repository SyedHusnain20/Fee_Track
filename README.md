# Step 9 — Attendance Scan Endpoint & Kiosk Page

Per your answer, the kiosk has a session selector — staff picks the active
category before scanning a batch. Two things fell out of that choice that
needed resolving before this could be built correctly:

1. **`AttendanceRecord` had no category column.** Without it, "already
   scanned today" couldn't be told apart from "already scanned for
   Coaching today" — a student legitimately attending both School and
   Coaching the same day would've looked like a duplicate scan. Added via
   migration (table's been empty since Step 5, so this is a safe, no-data
   change) — see `alembic/versions/b3f7a1d92e44_...py`.
2. **Server timezone.** `python:3.12-slim` doesn't ship IANA timezone data
   by default. Without an explicit zone, `datetime.now()` risks silently
   running in UTC — Pakistan is UTC+5, so every scan's on-time/late
   calculation would be wrong by exactly 5 hours. Fixed by hardcoding
   `Asia/Karachi` via `zoneinfo` in `attendance.py`, and adding the
   `tzdata` package so that zone actually resolves regardless of what the
   base image ships.

## What's new
- **The kiosk page** (`/kiosk`, fully public, no login) — a category
  selector plus a scan input built for a real USB/handheld QR scanner
  (which types into whatever has focus, followed by Enter). Shows a big
  colored result: green "On time," amber "Late," red for anything else
  (unrecognized code, inactive person, duplicate scan for that category
  today). Resets itself after 4 seconds for the next scan.
- **`POST /kiosk/scan`** — the actual write. Unauthenticated by design
  ("the attendance kiosk is not a role... physically secured at the school
  gate"). Returns just the scanned person's name + status — enough for
  gate staff to catch a mixed-up QR code, nothing beyond that single scan.
- **`/settings`** (admin-only) — set each category's start time and grace
  period. **Seeded with placeholder times, not your school's real
  schedule** — review these before trusting the kiosk for real attendance.

## Files, and where they go
```
app/models/attendance_record.py       → app/models/attendance_record.py       (overwrite — adds category column)
alembic/versions/b3f7a1d92e44_add_category_to_attendance_record.py → alembic/versions/ (new)
app/services/attendance_settings.py   → app/services/attendance_settings.py   (new)
app/services/attendance.py            → app/services/attendance.py            (new)
app/api/kiosk.py                      → app/api/kiosk.py                      (new)
app/api/settings.py                   → app/api/settings.py                   (new)
app/templates/kiosk/scan.html         → app/templates/kiosk/scan.html         (new folder)
app/templates/settings/list.html      → app/templates/settings/list.html      (new folder)
app/templates/base.html               → app/templates/base.html               (overwrite — adds Settings nav link)
app/templates/dashboard.html          → app/templates/dashboard.html          (overwrite — adds an "Open kiosk" card)
scripts/seed_reference_data.py        → scripts/seed_reference_data.py        (overwrite — adds attendance timing seed)
```

One addition on top of the above: nothing linked to `/kiosk` from inside the admin area, so staff would've had to know the URL by heart. The dashboard now has a third card — "Open kiosk ↗" — worth bookmarking directly on whatever device sits at the gate, rather than relying on this link every time.

## Two manual edits

**1. `requirements.txt`** — add:
```
tzdata
```
Then rebuild (new dependency):
```bash
docker compose up --build
```

**2. `app/main.py`** — add the two new routers:
```python
from app.api.kiosk import router as kiosk_router
from app.api.settings import router as settings_router

...
app.include_router(kiosk_router)
app.include_router(settings_router)
```

## Then, in order

```bash
# 1. rebuild (tzdata is new)
docker compose up --build

# 2. check current head before migrating
docker compose exec api alembic heads
# should print: 8f3d1a9b6c22 (head)

# 3. apply the new migration
docker compose exec api alembic upgrade head
# should now report: 8f3d1a9b6c22 -> b3f7a1d92e44

# 4. re-run the seed script — idempotent, only adds the new attendance-timing keys
docker compose exec api python scripts/seed_reference_data.py
```

## Verifying it works
1. **First, go to `/settings`** and set real start times for at least
   "School" (the placeholder default is 08:00 — change it if that's wrong,
   and set a real time for whichever category you'll test with).
2. Open `/kiosk` in a separate (or incognito) tab — confirm it does **not**
   redirect to `/login`. This one matters: if it does redirect, the kiosk
   isn't actually public and gate staff won't be able to use it without an
   admin account.
3. Pick a category, then manually type a real student's `qr_code` token
   into the scan field (grab one from the database, or note the value
   Step 7 Phase 1 generated) and press Enter — should show a green "On
   time" or amber "Late" result within a second or two, matching the
   category's configured start time + grace period.
4. Scan the **same token, same category** again — should get a red
   "already scanned for X today" message, not a duplicate row.
5. Scan the **same token, a different category** — should succeed. This is
   the one worth actually confirming, not trusting: it's exactly the
   scenario the new `category` column exists to support (one student, two
   legitimate sessions, same day).
6. Try a made-up token — "Unrecognized QR code," not a crash.
7. Check the database: `attendance_record` should now have the `category`
   column, and the two new partial unique indexes
   (`ix_attendance_one_scan_per_student_category_day` /
   `..._teacher_category_day`) should exist.
8. `ruff check .` and `pytest -v` still green.

## What's deliberately not in this step
- No rate-limiting or abuse protection on `/kiosk/scan` — Step 13
  (Security & Reliability Hardening) is where that belongs, same as CSRF
  and login throttling were deferred there back in Step 6.
- No audit-log entries for attendance scans — Key Design Principle #7
  scopes the mandatory hook to Enrollment and FeeCycle specifically, same
  reasoning already applied to CategoryFeeDefault in Phase 2.
- `academic_year_reset_month` is seeded but has no edit UI yet — that's
  Step 11's job, when the year-end archive job actually reads it.

## What's next
Step 10 (admin attendance reporting) is where all this scanned data
actually becomes visible to admins — view/export by date range, class, or
category. Say "Step 10" when you're ready.
