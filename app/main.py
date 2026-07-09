from fastapi import FastAPI

from app.core.config import settings

app = FastAPI(title=settings.APP_NAME)


@app.get("/health")
def health_check() -> dict:
    """Used by UptimeRobot (Section 10) and Docker healthchecks."""
    return {"status": "ok", "environment": settings.ENVIRONMENT}


# Routers get wired in as each module is built:
#   Step 6  -> app.api.auth (admin login/session)
#   Step 8  -> app.api.enrollment, app.api.fees
#   Step 9  -> app.api.attendance (kiosk scan endpoint)
#   Step 10 -> app.api.reports
#   Step 11 -> app.api.year_end
