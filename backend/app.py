from fastapi import FastAPI

from api.routers.auth.auth import router as auth_router
from api.routers.health import router as health_router

app = FastAPI(title="AssistMe API", version="0.1.0")
app.include_router(health_router)
app.include_router(auth_router)
