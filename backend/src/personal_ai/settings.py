"""Typed application configuration loaded from the environment."""

from functools import lru_cache

from pydantic import AnyHttpUrl, Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ContextBudgetInvalidError(Exception):
    """Invalid operator configuration, without exposing environment values."""


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
    max_context_tokens: int = Field(default=32_768, gt=0)
    max_response_tokens: int = Field(default=4_096, gt=0)
    context_safety_margin_tokens: int = Field(default=1_024, ge=0)
    summary_trigger_tokens: int = Field(default=12_000, gt=0)
    max_summary_tokens: int = Field(default=2_048, gt=0)
    context_inspection_enabled: bool = False
    memory_enabled: bool = False
    memory_extraction_enabled: bool = False
    memory_inspection_enabled: bool = False
    memory_embedding_model: str = Field(default="gemini-embedding-001", min_length=1)
    memory_embedding_dimensions: int = Field(default=768, gt=0, le=2048)
    memory_embedding_batch_size: int = Field(default=8, gt=0, le=100)
    memory_max_candidates_per_turn: int = Field(default=4, gt=0, le=16)
    memory_retrieval_candidate_limit: int = Field(default=20, gt=0, le=100)
    memory_retrieval_limit: int = Field(default=4, gt=0)
    memory_min_similarity: float = Field(default=0.8, ge=0, le=1)
    memory_max_context_tokens: int = Field(default=512, gt=0)
    memory_timeout_seconds: float = Field(default=5, gt=0, le=30)
    memory_sensitive_terms: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_context_budget(self) -> "Settings":
        available = self.max_context_tokens - self.max_response_tokens - self.context_safety_margin_tokens
        if available <= 0 or self.max_summary_tokens >= available:
            raise ValueError("context_budget_invalid")
        if self.summary_trigger_tokens > available:
            raise ValueError("context_budget_invalid")
        if self.memory_retrieval_limit > self.memory_retrieval_candidate_limit:
            raise ValueError("memory_configuration_invalid")
        if (self.memory_enabled or "memory_max_context_tokens" in self.model_fields_set) \
                and self.memory_max_context_tokens > available:
            raise ValueError("memory_configuration_invalid")
        return self

    cors_origins: list[AnyHttpUrl] = Field(default_factory=list)

    @property
    def allowed_web_origins(self) -> list[str]:
        """Return browser origins in the form expected by CORS middleware."""
        return [str(origin).rstrip("/") for origin in self.cors_origins]


@lru_cache
def get_settings() -> Settings:
    """Provide a single settings instance for dependency injection."""
    try:
        return Settings()
    except ValidationError as error:
        if "context_budget_invalid" in str(error):
            raise ContextBudgetInvalidError("context_budget_invalid") from error
        raise
