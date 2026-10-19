from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.exceptions import install_exception_handlers
from app.core.logging import configure_logging
from app.core.request_id import RequestContextMiddleware
from app.modules.auth.router import router as auth_router
from app.modules.users.router import router as users_router
from app.modules.projects.router import router as projects_router
from app.modules.workflows.router import router as workflows_router
from app.modules.issues.router import router as issues_router
from app.modules.issues.board_router import router as board_router
from app.modules.comments.router import router as comments_router
from app.modules.audit.router import router as audit_router
from app.modules.notifications.router import router as notifications_router
from app.modules.dashboards.router import router as dashboards_router
from app.modules.reports.router import router as reports_router

configure_logging()
app = FastAPI(title=settings.app_name, version="1.0.0")
install_exception_handlers(app)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in [auth_router, users_router, projects_router, workflows_router, issues_router, board_router,
               comments_router, audit_router, notifications_router, dashboards_router, reports_router]:
    app.include_router(router, prefix=settings.api_v1_prefix)


@app.get("/health")
async def health():
    return {"status": "ok"}
