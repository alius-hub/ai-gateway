import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE_MAP = {
    "dev": ".env.dev",
    "uat": ".env.uat",
    "prd": ".env.prd",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        env_prefix="AI_GATEWAY_",
        extra="ignore",
    )

    app_name: str = "AI Gateway"
    env: str = Field(default="dev")
    debug: bool = Field(default=True)
    app_port: int = Field(default=8001)
    api_prefix: str = "/api"
    admin_api_prefix: str = "/api/admin/v1"
    gateway_api_prefix: str = "/v1"
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/ai_gateway"
    )
    redis_url: str = Field(default="redis://localhost:6379/0")
    jwt_secret_key: str = Field(default="change-me-in-production")
    access_token_expire_minutes: int = Field(default=120)
    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
        ]
    )


@lru_cache
def get_settings() -> Settings:
    current_env = os.getenv("ENV", "dev").strip().lower() or "dev"
    env_file_name = ENV_FILE_MAP.get(current_env, ".env.dev")
    env_file_path = Path(__file__).resolve().parents[2] / env_file_name
    return Settings(_env_file=env_file_path)
