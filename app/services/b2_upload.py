"""Backblaze B2 upload — using b2sdk (already pinned in requirements.txt),
not boto3. Writes the workbook to a temp file rather than passing bytes
directly, since upload_local_file is the most stable, well-documented
b2sdk call across versions.
"""

import os
import tempfile
from io import BytesIO

from b2sdk.v2 import B2Api, InMemoryAccountInfo
from b2sdk.v2.exception import B2Error

from app.core.config import settings


class B2UploadError(Exception):
    """Raised on any failure. Callers must NOT clear AttendanceRecord
    unless upload_archive_to_b2 returns without raising."""


def upload_archive_to_b2(file_bytes: BytesIO, remote_filename: str) -> str:
    if not (settings.B2_KEY_ID and settings.B2_APPLICATION_KEY and settings.B2_BUCKET_NAME):
        raise B2UploadError("B2 credentials are not configured — check .env.")

    tmp_path: str | None = None
    try:
        info = InMemoryAccountInfo()
        b2_api = B2Api(info)
        b2_api.authorize_account("production", settings.B2_KEY_ID, settings.B2_APPLICATION_KEY)
        bucket = b2_api.get_bucket_by_name(settings.B2_BUCKET_NAME)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(file_bytes.getvalue())
            tmp_path = tmp.name

        file_version = bucket.upload_local_file(local_file=tmp_path, file_name=remote_filename)
    except B2Error as exc:
        raise B2UploadError(f"B2 upload failed: {exc}") from exc
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    return file_version.id_
