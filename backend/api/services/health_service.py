class HealthService:
    @staticmethod
    def get_status() -> dict[str, str]:
        return {"status": "ok"}
