# Step 8 — QR Code Images & Printable ID Cards

Roadmap describes this as "minor admin UI to display a generated roll
number/QR" — the token generation itself already happened in Step 7 Phase 1
(a Student/Teacher row couldn't be created without one, so it had to move
earlier). What was still missing was turning that token into an actual
scannable image, which is all this step does.

Went slightly beyond "just display it" to a printable ID card view too
(one click, opens in a new tab, has a Print button) — small enough to still
count as "minor," and genuinely useful once real students exist.

## Verified before delivery, not just assumed
Actually installed `qrcode[pil]` in a sandbox and generated a real PNG from
a test token to confirm the API and output before handing this over —
`qrcode.make(data, box_size=8, border=2)` → valid PNG bytes, confirmed via
the file's magic-number header. Latest stable version as of this build:
**`qrcode[pil]==8.2`**.

## Design notes
- **QR images render on the fly, nothing is stored.** Same token always
  produces the same image, so there's no file to keep in sync with the DB
  — one less thing that can drift.
- **A new standalone router (`app/api/id_cards.py`), not additions to
  students.py/teachers.py.** Both entities need near-identical
  qr-code.png + id-card routes, and this is a display concern, not CRUD —
  keeping it separate meant **zero changes to your existing
  students.py/teachers.py Python files**, only their templates.
- **QR image/ID card routes require admin login**, same as everything
  else. The `<img>` tags calling them sit on already-authenticated pages,
  and a same-site `<img src>` request carries the `SameSite=Lax` session
  cookie fine — this doesn't require any change to Step 6's cookie
  settings.
- **The QR encodes the raw token, not a URL.** Step 9's kiosk scan
  endpoint path isn't built yet; wrapping the token in a URL later, if
  that turns out to be the right shape, is a one-line change to
  `qr_image.py`, not a reprint of every already-issued QR code — the
  token itself doesn't change either way.

## Files, and where they go
```
app/services/qr_image.py              → app/services/qr_image.py
app/api/id_cards.py                   → app/api/id_cards.py
app/templates/id_cards/student_card.html → app/templates/id_cards/student_card.html (new folder)
app/templates/id_cards/teacher_card.html → app/templates/id_cards/teacher_card.html
app/templates/students/detail.html    → app/templates/students/detail.html   (overwrite — adds QR thumbnail + "Print ID card" link)
app/templates/teachers/list.html      → app/templates/teachers/list.html     (overwrite — adds "ID card" link)
```

## Two manual edits

**1. `requirements.txt`** — add:
```
qrcode[pil]==8.2
```
Then rebuild (new dependency, not just a bind-mounted code change):
```bash
docker compose up --build
```

**2. `app/main.py`** — add the new router:
```python
from app.api.id_cards import router as id_cards_router
...
app.include_router(id_cards_router)
```
No prefix on this router — its routes already spell out full paths
(`/students/{id}/qr-code.png`, `/teachers/{id}/qr-code.png`, etc.), so
inclusion order relative to your other routers doesn't matter; none of
these paths collide with anything already registered.

## Verifying it works
1. Open any student's detail page — a small QR thumbnail should now sit
   next to their name.
2. Click **Print ID card** — opens a clean, printable card (roll number,
   name, class, QR code) in a new tab. Click **Print this card** to confirm
   the browser print dialog looks right, and that the Print/Back buttons
   disappear from the print preview (that's the `@media print` rule).
3. Do the same from `/teachers` → **ID card** for a teacher.
4. Try loading a `qr-code.png` URL directly while logged out (or in an
   incognito tab) — should redirect to `/login`, not serve the image. This
   is the one worth actually testing, not trusting: it confirms tokens
   aren't fetchable by an unauthenticated request before Step 9's kiosk
   endpoint exists.
5. `ruff check .` and `pytest -v` still green.

## What's still ahead
Step 9 (attendance) is where these same tokens get scanned for real — the
unauthenticated, write-only kiosk endpoint that logs arrival time and
computes on-time/late against category start times + grace periods.
