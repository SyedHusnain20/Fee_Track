"""Unique QR scan-token generation.

Deliberately a random opaque token, not derived from roll_number/staff_id —
the attendance kiosk endpoint (Step 9) is unauthenticated and write-only, so
a random unguessable token means a scan can't be spoofed by trying nearby
roll numbers. Turning this token into an actual scannable QR *image* (via
the `qrcode` library) stays Step 8's job.
"""

import secrets


def generate_qr_token() -> str:
    return secrets.token_urlsafe(16)
