"""QR code image rendering — Step 8, completing the "QR code + roll-number
generation" roadmap item. The token generation itself was pulled forward
into Step 7 Phase 1 (Student/Teacher rows couldn't be created without one);
what was still missing was turning that token into an actual scannable
image.

Renders on the fly from the already-stored qr_code token — nothing new is
generated or persisted here. The same token always produces the same
image, so there's no image file to store or keep in sync with the DB.

Deliberately encodes just the raw token string, not a URL — Step 9's exact
kiosk scan endpoint path isn't built yet, and wrapping the token in a URL
later (if that turns out to be the right shape for the kiosk) is a one-line
change here, not a re-generation of every already-printed QR code, since
the underlying token itself doesn't change either way.
"""

import io

import qrcode


def render_qr_png(data: str) -> bytes:
    img = qrcode.make(data, box_size=8, border=2)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()
