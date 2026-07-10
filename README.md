# Raabta — School Management System

Solo-developer school management system: attendance (QR-based, arrival-time only) + fee management, admin-only, no teacher/parent-facing features (yet — see reserved extension points).

## Stack

FastAPI · SQLModel · Alembic · PostgreSQL · Docker Compose · Nginx · Hetzner VPS

## Local development

1. Copy the env template and fill in real values:
   ```bash
   cp .env.example .env
   ```
2. Build and start everything:
   ```bash
   docker compose up --build
   ```
3. Check it's alive:
   ```bash
   curl http://localhost/health
   ```

## Project layout

```
app/
  core/          # settings, DB engine/session
  models/        # SQLModel table classes (Step 5)
  api/           # routers (Steps 6, 8, 9, 10, 11)
  main.py        # FastAPI app instance
alembic/         # migrations — env.py reads DATABASE_URL from app.core.config
nginx/           # reverse proxy in front of the api container
docker-compose.yml
Dockerfile
```

## Running migrations

Once models exist (Step 5):
```bash
docker compose exec api alembic revision --autogenerate -m "add core models"
docker compose exec api alembic upgrade head
```

## Repo setup (Step 4)

This folder is already a git repo with Step 3 committed. To push it to GitHub:

1. Create a new **empty** repository on GitHub (no README/license/gitignore — you already have one). Don't make it public unless you're comfortable with the client's data model being visible; private is the safer default for a school system.
2. Connect and push:
   ```bash
   git remote add origin https://github.com/<your-username>/raabta.git
   git branch -M main
   git push -u origin main
   ```
3. CI runs automatically from that point on — every push and PR to `main` triggers `.github/workflows/ci.yml`, which lints with ruff and runs the test suite. Check the "Actions" tab on GitHub after your first push to confirm it goes green.

## Running lint/tests locally

Before pushing, you can run exactly what CI runs:
```bash
pip install -r requirements.txt -r requirements-dev.txt
ruff check .
pytest -v
```

## Backblaze B2 setup (for nightly backups)

1. Sign up at [backblaze.com](https://www.backblaze.com/cloud-storage) if you haven't already (free tier includes 10GB, plenty for these dumps).
2. Create a **private** bucket, e.g. `raabta-backups`.
3. Under Bucket Settings, add a **Lifecycle Rule**: "Keep only the last N days" (30 is reasonable) so old dumps auto-delete instead of accumulating storage cost forever.
4. Go to **App Keys** → **Add a New Application Key**, scope it to just the `raabta-backups` bucket (not your whole account — smaller blast radius if a key ever leaks).
5. Copy the `keyID` and `applicationKey` into your `.env`:
   ```
   B2_KEY_ID=<your keyID>
   B2_APPLICATION_KEY=<your applicationKey>
   B2_BUCKET_NAME=raabta-backups
   ```
6. Test it manually:
   ```bash
   docker compose exec api python scripts/backup_to_b2.py
   ```
   Check the bucket in the B2 web console — you should see a new file under `nightly/`.

## Scheduling nightly backups

This only matters once you're on the actual VPS (Step 15) — no need to set this up on your dev machine. On the server, add a cron job:
```bash
crontab -e
```
```
0 2 * * * cd /path/to/raabta && docker compose exec -T api python scripts/backup_to_b2.py >> /var/log/raabta_backup.log 2>&1
```
Runs at 2am server time, after the school day is well over.



See the 15-step roadmap (Section 12 of the project spec, as revised) — this scaffold covers Step 3. Step 5 adds the actual model files under `app/models/`.

# Raabta — School Management System

Solo-developer school management system: attendance (QR-based, arrival-time only) + fee management, admin-only, no teacher/parent-facing features (yet — see reserved extension points).

## Stack

FastAPI · SQLModel · Alembic · PostgreSQL · Docker Compose · Nginx · Hetzner VPS

## Local development

1. Copy the env template and fill in real values:
   ```bash
   cp .env.example .env
   ```
2. Build and start everything:
   ```bash
   docker compose up --build
   ```
3. Check it's alive:
   ```bash
   curl http://localhost/health
   ```

## Project layout

```
app/
  core/          # settings, DB engine/session
  models/        # SQLModel table classes (Step 5)
  api/           # routers (Steps 6, 8, 9, 10, 11)
  main.py        # FastAPI app instance
alembic/         # migrations — env.py reads DATABASE_URL from app.core.config
nginx/           # reverse proxy in front of the api container
docker-compose.yml
Dockerfile
```

## Running migrations

Once models exist (Step 5):
```bash
docker compose exec api alembic revision --autogenerate -m "add core models"
docker compose exec api alembic upgrade head
```

## Where this project is headed

See the 15-step roadmap (Section 12 of the project spec, as revised) — this scaffold covers Step 3. Step 5 adds the actual model files under `app/models/`.
