# Fee Track

A self-hosted fee, attendance, and staff-management system for a school
running both a regular School program and an Academy (Coaching / English /
Computer) side, built on FastAPI, PostgreSQL, and server-rendered
HTML/HTMX — no separate frontend to build or deploy.

## What it does

- **Students & enrollments** — one student record per child, with
  independent enrollments per fee category (School, Coaching, English,
  Computer). Fees are class-banded (e.g. Foundation vs. Class 9–10 pay
  different School rates) and each student can carry a single overall
  discount (fixed or percentage).
- **Fee cycles & invoices** — generate a month's fee cycles for every
  active student in one action, mark cycles paid, and produce a proper
  invoice: a letterhead-style PDF (server-rendered, not a browser
  print-to-PDF capture) and an 80mm thermal-receipt version for a bill
  printer, from the same underlying data.
- **Attendance kiosk** — a public, unauthenticated scan page for a
  gate-side QR scanner or keypad, covering both School and Academy
  sessions, with on-time/late judged against admin-configured start times
  and grace periods, plus a manual-entry fallback for authenticated staff.
- **Teacher salary** — computed from attendance (working days minus
  absences, split proportionally for teachers who work both School and
  Academy).
- **Admin accounts** — self-service signup with super-admin
  approve/reject, session-based auth (Argon2 password hashing, DB-backed
  sessions, CSRF protection, login/signup throttling).
- **Audit log** — Enrollment, FeeCycle, and admin-account lifecycle
  changes are recorded with before/after snapshots.
- **Year-end rollover & attendance archive** — promote every active
  student a class level (with graduating students deactivated
  automatically), and archive + reset the attendance table once it's
  grown large, backed up to Backblaze B2 first.
- **Reports** — per-student fee history and a rolling attendance view.

## Tech stack

FastAPI · SQLModel (SQLAlchemy) · PostgreSQL · Alembic · Jinja2 + HTMX ·
WeasyPrint (PDF invoices) · Argon2 (password hashing) · Docker + nginx

## Project layout

```
app/
  api/         one router per feature area (students, fee_cycles, kiosk, ...)
  core/        config, database session, auth/CSRF/security, timezone
  models/      SQLModel tables
  services/    business logic — fee calculation, attendance, salary, audit, ...
  templates/   Jinja2 templates, one folder per feature area
alembic/       migration history
scripts/       seed_reference_data.py — one-off reference-data seeding
nginx/         reverse proxy config
tests/         pytest suite
```

## Running it locally

Requires Docker and Docker Compose.

1. Create a `.env` file in the project root with at least:
   ```env
   SECRET_KEY=some-long-random-string
   POSTGRES_PASSWORD=some-password
   ```
   (`POSTGRES_USER`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT` all
   have sensible local defaults — see `app/core/config.py` if you need to
   override any of them. If you're pointing at a hosted Postgres instead
   — e.g. Neon — set `DATABASE_URL_OVERRIDE` to the full connection
   string instead of the `POSTGRES_*` fields.)

2. Build and start everything:
   ```bash
   docker compose up --build
   ```

3. Apply migrations:
   ```bash
   docker compose exec api alembic upgrade head
   ```

4. Seed fixed reference data (class levels, fee bands, attendance
   settings) — safe to re-run, it only adds what's missing:
   ```bash
   docker compose exec api python scripts/seed_reference_data.py
   ```

5. Visit `/signup` to create the first admin account, then approve it —
   the very first account needs a super admin to already exist to
   approve it, so for a brand-new install promote it directly in the
   database:
   ```bash
   docker compose exec db psql -U raabta -d raabta -c \
     "UPDATE admin_user SET is_approved = true, is_super_admin = true WHERE email = 'you@example.com';"
   ```

6. Before onboarding real students, go to **Category Fees** and set the
   real per-band amounts — they seed as placeholders (Rs 1000, or Rs 0 if
   a fresh migration inserted them directly) and won't reflect your
   school's actual pricing until reviewed.

For a hardened production overlay (drops local bind-mounts, keeps
uvicorn single-process), see the notes at the top of
`docker-compose.prod.yml`.

## Running tests / linting

```bash
docker compose exec api pytest -v
docker compose exec api ruff check .
```

## Health check

`GET /health` — used by the `api` container's own Docker healthcheck.

---

Powered by: R&R Digital Solutions
Contact: 03126641281 | HasnainZainulabdin@gmail.com
Website: www.rrdigitalsolutions.org
