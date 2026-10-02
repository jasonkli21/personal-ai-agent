"""Typed application configuration loaded from the environment."""

import math
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
    memory_experiment_variant: str = Field(
        default="fixed", pattern=r"^(fixed|scored|consolidated)$"
    )
    memory_scoring_policy_version: str = Field(default="score-v1", min_length=1, max_length=100)
    memory_score_similarity_weight: float = Field(default=0.50, ge=0, le=1)
    memory_score_importance_weight: float = Field(default=0.15, ge=0, le=1)
    memory_score_recency_weight: float = Field(default=0.15, ge=0, le=1)
    memory_score_frequency_weight: float = Field(default=0.10, ge=0, le=1)
    memory_score_confidence_weight: float = Field(default=0.10, ge=0, le=1)
    memory_recency_half_life_days: float = Field(default=90, gt=0, le=36500)
    memory_consolidation_enabled: bool = False
    memory_consolidation_max_sources: int = Field(default=4, ge=2, le=4)
    memory_contradiction_automation_enabled: bool = False
    memory_forgetting_enabled: bool = False
    memory_lifecycle_worker_enabled: bool = False
    memory_lifecycle_inspection_enabled: bool = False
    memory_lifecycle_topic: str = Field(default="personal-ai-async", min_length=1, max_length=200)
    memory_job_max_attempts: int = Field(default=3, ge=1, le=10)
    memory_job_execution_seconds: int = Field(default=30, ge=1, le=30)
    memory_job_lease_seconds: int = Field(default=60, ge=30, le=300)
    memory_job_candidate_limit: int = Field(default=40, ge=1, le=100)

    @model_validator(mode="after")
    def validate_context_budget(self) -> "Settings":
        available = (
            self.max_context_tokens - self.max_response_tokens - self.context_safety_margin_tokens
        )
        if available <= 0 or self.max_summary_tokens >= available:
            raise ValueError("context_budget_invalid")
        if self.summary_trigger_tokens > available:
            raise ValueError("context_budget_invalid")
        if self.memory_retrieval_limit > self.memory_retrieval_candidate_limit:
            raise ValueError("memory_configuration_invalid")
        weights = (
            self.memory_score_similarity_weight,
            self.memory_score_importance_weight,
            self.memory_score_recency_weight,
            self.memory_score_frequency_weight,
            self.memory_score_confidence_weight,
        )
        if self.memory_scoring_policy_version != "score-v1":
            raise ValueError("memory_configuration_invalid")
        if (any(not math.isfinite(weight) for weight in weights) or sum(weights) <= 0
                or self.memory_job_execution_seconds >= self.memory_job_lease_seconds):
            raise ValueError("memory_configuration_invalid")
        if (
            self.memory_enabled or "memory_max_context_tokens" in self.model_fields_set
        ) and self.memory_max_context_tokens > available:
            raise ValueError("memory_configuration_invalid")
        gated = (
            self.memory_consolidation_enabled,
            self.memory_contradiction_automation_enabled,
            self.memory_forgetting_enabled,
            self.memory_lifecycle_worker_enabled,
            self.memory_lifecycle_inspection_enabled,
        )
        if any(gated) and not self.memory_enabled:
            raise ValueError("memory_configuration_invalid")
        if self.memory_experiment_variant != "fixed" and not self.memory_enabled:
            raise ValueError("memory_configuration_invalid")
        if (
            self.memory_contradiction_automation_enabled or self.memory_forgetting_enabled
        ) and not self.memory_lifecycle_worker_enabled:
            raise ValueError("memory_configuration_invalid")
        if self.memory_consolidation_enabled and not self.memory_lifecycle_worker_enabled:
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
