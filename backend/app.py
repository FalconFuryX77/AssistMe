"""AssistMe API — FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers.auth.auth import router as auth_router
from api.routers.assistance_requests import router as assistance_requests_router
from api.routers.contacts import router as contacts_router
from api.routers.context_engine import router as context_engine_router
from api.routers.device_ws import router as device_ws_router
from api.routers.guides import router as guides_router
from api.routers.health import router as health_router
from api.routers.help_flow import router as help_flow_router
from api.routers.intelligent_assistance import router as intelligent_assistance_router
from api.routers.policy_engine import router as policy_engine_router
from api.routers.sessions import router as sessions_router
from api.routers.session_ws import router as session_ws_router
from api.routers.trusted_devices import router as trusted_devices_router
from api.routers.users import router as users_router
from core.config import settings

#: Prefix for framework endpoints that are not part of the consumer product.
INTERNAL_PREFIX = "/internal"
from core.database import create_tables, engine

# Ensure all models are imported so SQLAlchemy knows about them
import models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run development bootstrap only; production uses migrations."""
    if settings.AUTO_CREATE_TABLES:
        await create_tables()
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="One-tap remote assistance for trusted family and friends: screen sharing, voice, drawing, and optional helpee-approved control.",
    lifespan=lifespan,
    docs_url=None if settings.IS_PRODUCTION else "/docs",
    redoc_url=None if settings.IS_PRODUCTION else "/redoc",
    openapi_url=None if settings.IS_PRODUCTION else "/openapi.json",
)

# --- CORS Middleware for Internet Deployment ---
# Allows cross-origin requests from configured domains (or "*" for dev).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(sessions_router)
app.include_router(session_ws_router)
app.include_router(device_ws_router)
app.include_router(help_flow_router)
app.include_router(trusted_devices_router)
app.include_router(assistance_requests_router)
app.include_router(contacts_router)
app.include_router(users_router)
app.include_router(context_engine_router, prefix=INTERNAL_PREFIX)
app.include_router(policy_engine_router, prefix=INTERNAL_PREFIX)
app.include_router(intelligent_assistance_router)
app.include_router(guides_router)

