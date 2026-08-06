from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
def register() -> dict[str, str]:
    return {"message": "registration endpoint placeholder"}


@router.post("/login")
def login() -> dict[str, str]:
    return {"message": "login endpoint placeholder"}
