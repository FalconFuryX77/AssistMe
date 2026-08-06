from fastapi import APIRouter

from api.schemas.auth import LoginRequest, RegisterRequest
from api.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=dict[str, str])
def register(payload: RegisterRequest) -> dict[str, str]:
    return AuthService.register(payload.email, payload.password)


@router.post("/login", response_model=dict[str, str])
def login(payload: LoginRequest) -> dict[str, str]:
    return AuthService.login(payload.email, payload.password)
