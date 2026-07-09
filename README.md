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
