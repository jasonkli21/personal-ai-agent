"""Typed application configuration loaded from the environment."""

from functools import lru_cache

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration shared by the Phase 1 application boundaries.

    Values deliberately come only from the environment (or a local untracked
    ``.env`` file). Provider credentials are represented as ``SecretStr`` so
    routine logging and repr output cannot disclose them.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ai_provider: str = Field(min_length=1)
    ai_model: str = Field(min_length=1)
    ai_api_key: SecretStr = Field(default=SecretStr(""))
    firestore_project_id: str | None = None
    firestore_emulator_host: str | None = None
    request_timeout_seconds: float = Field(default=30, gt=0, le=300)
    max_phase_1_history_messages: int = Field(default=40, ge=1, le=200)
    cors_origins: list[AnyHttpUrl] = Field(default_factory=list)

    @property
    def allowed_web_origins(self) -> list[str]:
        """Return browser origins in the form expected by CORS middleware."""
        return [str(origin).rstrip("/") for origin in self.cors_origins]


@lru_cache
def get_settings() -> Settings:
    """Provide a single settings instance for dependency injection."""
    return Settings()
