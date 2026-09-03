"""School branding for printable documents (invoices, payment receipts).

The logo is embedded as a base64 data URI directly in the HTML rather
than referenced by a /static/... URL, because two of the three places
this HTML gets rendered have no way to fetch a relative URL:

  - weasyprint's HTML(string=...).write_pdf() (see app/api/fee_cycles.py)
    is called with no base_url, so a relative image src simply fails to
    resolve -- there's no server context for it to fetch against.
  - The thermal print popup (window.open(..., 'width=420,height=640'))
    is a same-origin page so /static/ WOULD work there, but keeping one
    embedding strategy for all three render paths (screen, thermal
    print, PDF) means the logo can never go missing in just one of them.

get_logo_data_uri() reads and encodes the file once per process
(functools.lru_cache) rather than on every request -- it's a small,
never-changing static asset.
"""

import base64
from functools import lru_cache
from pathlib import Path

_LOGO_PATH = Path(__file__).resolve().parent.parent / "static" / "branding" / "apex_academy_logo.png"


@lru_cache(maxsize=1)
def get_logo_data_uri() -> str:
    data = _LOGO_PATH.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{encoded}"
