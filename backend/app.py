"""AssistMe API — FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routers.auth.auth import router as auth_router
from api.routers.contacts import router as contacts_router
from api.routers.health import router as health_router
from api.routers.users import router as users_router
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
    version="0.2.0",
    description="Adaptive Context-Aware Secure Assistance Framework",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(contacts_router)
