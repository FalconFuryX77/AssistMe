"""AssistMe API — FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers.auth.auth import router as auth_router
from api.routers.assistance_requests import router as assistance_requests_router
from api.routers.contacts import router as contacts_router
from api.routers.context_engine import router as context_engine_router
from api.routers.health import router as health_router
from api.routers.intelligent_assistance import router as intelligent_assistance_router
from api.routers.policy_engine import router as policy_engine_router
from api.routers.sessions import router as sessions_router
from api.routers.session_ws import router as session_ws_router
from api.routers.trusted_devices import router as trusted_devices_router
from api.routers.users import router as users_router
from core.config import settings
from core.database import create_tables

# Ensure all models are imported so SQLAlchemy knows about them
import models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create database tables on startup (development convenience)."""
    await create_tables()
    yield


app = FastAPI(
    title="AssistMe API",
    version="0.4.0",
    description="Adaptive Context-Aware Secure Assistance Framework",
    lifespan=lifespan,
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
app.include_router(users_router)
app.include_router(contacts_router)
app.include_router(sessions_router)
app.include_router(session_ws_router)
app.include_router(context_engine_router)
app.include_router(policy_engine_router)
app.include_router(intelligent_assistance_router)
app.include_router(trusted_devices_router)
app.include_router(assistance_requests_router)
