"""
Dumps the Postgres database and uploads it to Backblaze B2.

Intended to run nightly via cron once deployed (see README's
"Scheduling nightly backups" section). Safe to run manually to test:

    docker compose exec api python scripts/backup_to_b2.py

Requires B2_KEY_ID, B2_APPLICATION_KEY, and B2_BUCKET_NAME to be set in .env —
see README's "Backblaze B2 setup" section for how to create these.
"""

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from b2sdk.v2 import B2Api, InMemoryAccountInfo

from app.core.config import settings

BACKUP_DIR = Path("/tmp/raabta_backups")


def create_dump() -> Path:
    """Runs pg_dump against the configured database and gzips the result."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    raw_path = BACKUP_DIR / f"raabta_{timestamp}.sql"
    gz_path = raw_path.with_suffix(".sql.gz")

    pg_dump_cmd = [
        "pg_dump",
        f"--host={settings.POSTGRES_HOST}",
        f"--port={settings.POSTGRES_PORT}",
        f"--username={settings.POSTGRES_USER}",
        f"--dbname={settings.POSTGRES_DB}",
        "--no-password",
        "--format=plain",
        "--file",
        str(raw_path),
    ]

    result = subprocess.run(
        pg_dump_cmd,
        env={"PGPASSWORD": settings.POSTGRES_PASSWORD},
    )
    if result.returncode != 0:
        raise RuntimeError(
            "pg_dump failed — check POSTGRES_HOST/PORT/USER/PASSWORD in .env "
            "and that the db container is reachable."
        )

    subprocess.run(["gzip", "-f", str(raw_path)], check=True)
    return gz_path


def upload_to_b2(dump_path: Path) -> None:
    if not (settings.B2_KEY_ID and settings.B2_APPLICATION_KEY and settings.B2_BUCKET_NAME):
        raise RuntimeError(
            "B2 credentials are missing from .env — see README's "
            "'Backblaze B2 setup' section."
        )

    info = InMemoryAccountInfo()
    b2_api = B2Api(info)
    b2_api.authorize_account("production", settings.B2_KEY_ID, settings.B2_APPLICATION_KEY)
    bucket = b2_api.get_bucket_by_name(settings.B2_BUCKET_NAME)

    bucket.upload_local_file(
        local_file=str(dump_path),
        file_name=f"nightly/{dump_path.name}",
    )
    print(f"Uploaded {dump_path.name} to B2 bucket '{settings.B2_BUCKET_NAME}'")


def main() -> None:
    dump_path = create_dump()
    try:
        upload_to_b2(dump_path)
    finally:
        dump_path.unlink(missing_ok=True)  # don't accumulate dumps inside the container


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — top-level script, want any failure visible in cron logs
        print(f"Backup failed: {exc}", file=sys.stderr)
        sys.exit(1)
