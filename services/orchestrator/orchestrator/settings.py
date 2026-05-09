from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    orchestrator_port: int = 8081

    reliability_url: str = "http://reliability:8082"
    guardrails_url: str = "http://guardrails:8083"
    memory_url: str = "http://memory:8084"
    replay_url: str = "http://replay:8085"
    chaos_url: str = "http://chaos:8086"

    postgres_dsn: str = "postgresql://aegis:devonly_change_me@postgres:5432/aegisflow"
    nats_url: str = "nats://nats:4222"
    nats_stream: str = "AEGIS"

    circuit_breaker_threshold: float = 0.5
    circuit_breaker_window_sec: float = 30.0
    circuit_breaker_cooldown_sec: float = 15.0


def load_settings() -> Settings:
    return Settings()
