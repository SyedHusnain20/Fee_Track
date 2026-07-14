from fastapi import FastAPI

from app.core.config import settings
from app.api.auth import router as auth_router
from app.api.admin_accounts import router as admin_accounts_router
from app.api.auth import router as auth_router
from app.api.admin_accounts import router as admin_accounts_router
from app.api.dashboard import router as dashboard_router
from app.api.students import router as students_router
from app.api.teachers import router as teachers_router
from app.api.auth import router as auth_router
from app.api.admin_accounts import router as admin_accounts_router
from app.api.dashboard import router as dashboard_router
from app.api.students import router as students_router
from app.api.teachers import router as teachers_router
from app.api.enrollments import router as enrollments_router
from app.api.category_fees import router as category_fees_router
from app.api.auth import router as auth_router
from app.api.admin_accounts import router as admin_accounts_router
from app.api.dashboard import router as dashboard_router
from app.api.students import router as students_router
from app.api.teachers import router as teachers_router
from app.api.enrollments import router as enrollments_router
from app.api.category_fees import router as category_fees_router
from app.api.fee_cycles import router as fee_cycles_router
from app.api.id_cards import router as id_cards_router


app = FastAPI(title=settings.APP_NAME)

app.include_router(auth_router)
app.include_router(admin_accounts_router)
app.include_router(dashboard_router)
app.include_router(students_router)
app.include_router(teachers_router)
app.include_router(auth_router)
app.include_router(admin_accounts_router)
app.include_router(dashboard_router)
app.include_router(students_router)
app.include_router(teachers_router)
app.include_router(enrollments_router)
app.include_router(category_fees_router)
app.include_router(auth_router)
app.include_router(admin_accounts_router)
app.include_router(dashboard_router)
app.include_router(students_router)
app.include_router(teachers_router)
app.include_router(enrollments_router)
app.include_router(category_fees_router)
app.include_router(fee_cycles_router)
app.include_router(auth_router)
app.include_router(admin_accounts_router)
app.include_router(id_cards_router)


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
