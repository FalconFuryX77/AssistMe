import hashlib
import secrets


class AuthService:
    @staticmethod
    def register(email: str, password: str) -> dict[str, str]:
        token = hashlib.sha256(f"{email}:{password}:{secrets.token_hex(8)}".encode()).hexdigest()
        return {"access_token": token, "token_type": "bearer"}

    @staticmethod
    def login(email: str, password: str) -> dict[str, str]:
        token = hashlib.sha256(f"{email}:{password}:{secrets.token_hex(8)}".encode()).hexdigest()
        return {"access_token": token, "token_type": "bearer"}
