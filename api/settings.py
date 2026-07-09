from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": .env 에 API_ 접두사 외 키(OCIO_DB_* 등 시크릿)가 공존 (2026-07-09)
    model_config = SettingsConfigDict(env_file=".env", env_prefix="API_", extra="ignore")

    env: str = "dev"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    # DB 접속정보는 modules/data_loader.py::DB_CONFIG + get_connection 재사용.
    # api/settings.py에 중복 선언 금지 (Day 0 원칙).


@lru_cache
def get_settings() -> Settings:
    return Settings()
