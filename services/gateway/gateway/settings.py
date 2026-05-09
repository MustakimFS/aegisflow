from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gateway_port: int = 8080

    orchestrator_url: str = "http://orchestrator:8081"
    replay_url: str = "http://replay:8085"

    redis_url: str = "redis://redis:6379/0"
    rate_limit_rps: int = 50
    rate_limit_burst: int = 100

    jwt_secret: str = "devonly_change_me"
    jwt_issuer: str = "aegisflow.local"
    jwt_audience: str = "aegisflow.api"
    jwt_algorithm: str = "HS256"

    log_level: str = "INFO"


def load_settings() -> Settings:
    return Settings()
