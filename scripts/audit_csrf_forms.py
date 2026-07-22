"""One-off audit script — finds every <form method="post"> block across all
templates that's missing csrf_token. Not a permanent script; delete after
use. Correctly skips login.html and kiosk/scan.html, which are
intentionally exempt from CSRF (see app/core/csrf.py).

Usage:
    docker compose exec api python scripts/audit_csrf_forms.py
"""
import re
from pathlib import Path

TEMPLATES_DIR = Path("app/templates")
EXEMPT_FILES = {"login.html", "scan.html"}

# Matches a <form ...method="post"...> up through its closing </form>,
# non-greedy so multiple forms in one file are found separately.
FORM_PATTERN = re.compile(
    r'<form\b[^>]*\bmethod=["\']post["\'][^>]*>.*?</form>',
    re.IGNORECASE | re.DOTALL,
)


def main() -> None:
    problems = []
    checked_forms = 0

    for html_file in sorted(TEMPLATES_DIR.rglob("*.html")):
        if html_file.name in EXEMPT_FILES:
            continue

        content = html_file.read_text(encoding="utf-8")
        forms = FORM_PATTERN.findall(content)

        for i, form_block in enumerate(forms, start=1):
            checked_forms += 1
            if "csrf_token" not in form_block:
                # Grab the action="..." for a human-readable pointer
                action_match = re.search(r'action=["\']([^"\']*)["\']', form_block)
                action = action_match.group(1) if action_match else "(no action attr)"
                problems.append((str(html_file), i, action))

    print(f"Checked {checked_forms} POST form(s) across templates (excluding {EXEMPT_FILES}).\n")

    if not problems:
        print("All POST forms have csrf_token. Nothing to fix.")
        return

    print(f"MISSING csrf_token in {len(problems)} form(s):\n")
    for filepath, form_index, action in problems:
        print(f"  {filepath}  (form #{form_index}, action=\"{action}\")")


if __name__ == "__main__":
    main()
