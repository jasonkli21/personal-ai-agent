"""Typed application configuration loaded from the environment."""

import math
import os
from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, AnyHttpUrl, Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SensitivityCeiling = Literal["public", "personal", "sensitive", "restricted"]


class ContextBudgetInvalidError(Exception):
    """Invalid operator configuration, without exposing environment values."""


class Settings(BaseSettings):
    """Configuration shared by API, worker, and provider boundaries.

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
    # Phase 17 reference adapters stay inactive until an operator records
    # account/model-specific cost, privacy, and compatibility preflight evidence.
    groq_adapter_enabled: bool = False
    groq_model: str = Field(default="", max_length=200)
    groq_api_key: SecretStr = Field(default=SecretStr(""))
    groq_free_tier_verified: bool = False
    groq_privacy_approved: bool = False
    groq_privacy_max_sensitivity: SensitivityCeiling = "public"
    groq_approved_model_aliases: tuple[str, ...] = Field(default=(), max_length=8)
    groq_structured_output_verified: bool = False
    groq_preflight_reference: str = Field(default="", max_length=500)
    cloudflare_adapter_enabled: bool = False
    cloudflare_account_id: str = Field(default="", max_length=64)
    cloudflare_model: str = Field(default="", max_length=200)
    cloudflare_api_token: SecretStr = Field(default=SecretStr(""))
    cloudflare_free_tier_verified: bool = False
    cloudflare_privacy_approved: bool = False
    cloudflare_privacy_max_sensitivity: SensitivityCeiling = "public"
    cloudflare_approved_model_aliases: tuple[str, ...] = Field(default=(), max_length=8)
    cloudflare_structured_output_verified: bool = False
    cloudflare_preflight_reference: str = Field(default="", max_length=500)
    gcp_project_id: str = Field(default="", max_length=200)
    persistence_local_postgres_dsn: SecretStr = Field(
        default=SecretStr(
            "postgresql://personal_ai:personal_ai_local_only@127.0.0.1:54329/personal_ai"
        )
    )
    persistence_local_dynamodb_endpoint: str = Field(
        default="http://127.0.0.1:8000", min_length=1, max_length=300
    )
    app_environment: str = Field(default="local", pattern=r"^(local|test|staging|production)$")
    # Deployed runtime persistence uses the verified Neon pooler and federated AWS role.
    p10_cloud_adapters_configured: bool = False
    p10_neon_runtime_dsn: SecretStr = Field(default=SecretStr(""))
    p10_neon_pool_max_size: int = Field(default=4, ge=1, le=4)
    p10_dynamodb_region: str = Field(default="us-east-1", min_length=1, max_length=32)
    p10_dynamodb_table_name: str = Field(default="personal-ai-runtime-v1", min_length=3, max_length=255)
    p10_dynamodb_role_arn: str = Field(default="", max_length=600)
    p10_dynamodb_identity_token_audience: str = Field(default="", max_length=500)
    auth_mode: str = Field(default="development", pattern=r"^(development|google_oidc)$")
    auth_required: bool = False
    auth_issuer: str = Field(default="https://accounts.google.com", min_length=1, max_length=200)
    auth_audience: str = Field(default="", max_length=500)
    auth_allowed_emails: tuple[str, ...] = Field(default=(), max_length=1)
    auth_hosted_domain: str = Field(default="", max_length=253)
    auth_recent_token_seconds: int = Field(default=300, ge=60, le=900)
    worker_push_auth_required: bool = False
    worker_push_audience: str = Field(default="", max_length=500)
    worker_push_service_account: str = Field(default="", max_length=254)
    worker_maintenance_auth_required: bool = False
    worker_maintenance_audience: str = Field(default="", max_length=500)
    worker_maintenance_service_account: str = Field(default="", max_length=254)
    observability_redaction_version: str = Field(
        default="redaction-v1", min_length=1, max_length=100
    )
    api_rate_limit_per_minute: int = Field(default=60, ge=1, le=10000)
    provider_calls_per_day_limit: int = Field(default=100, ge=1, le=100000)
    input_tokens_per_day_limit: int = Field(default=200000, ge=1, le=100000000)
    chat_kill_switch_enabled: bool = False
    research_kill_switch_enabled: bool = False
    worker_kill_switch_enabled: bool = False
    external_providers_kill_switch_enabled: bool = False
    maintenance_enabled: bool = False
    maintenance_batch_size: int = Field(default=40, ge=1, le=100)
    export_enabled: bool = False
    deletion_enabled: bool = False
    deletion_grace_period_days: int = Field(default=7, ge=1, le=90)
    export_max_records: int = Field(default=5000, ge=1, le=50000)
    export_max_bytes: int = Field(default=8_388_608, ge=65536, le=33_554_432)
    request_timeout_seconds: float = Field(default=30, gt=0, le=300)
    max_context_tokens: int = Field(default=32_768, gt=0)
    max_response_tokens: int = Field(default=4_096, gt=0)
    context_safety_margin_tokens: int = Field(default=1_024, ge=0)
    context_profile_max_tokens: int = Field(default=512, ge=1, le=32_768)
    context_domain_max_tokens: int = Field(default=2_048, ge=1, le=32_768)
    context_tool_max_tokens: int = Field(default=1_024, ge=1, le=32_768)
    context_client_max_tokens: int = Field(default=512, ge=1, le=32_768)
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

    research_storage: str = Field(default="postgres", pattern=r"^(postgres|memory)$")
    research_enabled: bool = False
    research_inspection_enabled: bool = False
    research_search_adapter: str = Field(default="fake", pattern=r"^(fake|brave)$")
    research_planner: str = Field(default="deterministic", pattern=r"^deterministic$")
    research_reranker: str = Field(default="deterministic", pattern=r"^deterministic$")
    research_provider_storage_approved: bool = False
    research_api_key: SecretStr = Field(default=SecretStr(""))
    research_max_queries: int = Field(default=1, ge=1, le=3)
    research_max_sources: int = Field(default=8, ge=1, le=12)
    research_max_response_bytes: int = Field(default=131072, ge=1024, le=262144)
    research_max_redirects: int = Field(default=0, ge=0, le=0)
    research_max_concurrency: int = Field(default=1, ge=1, le=1)
    research_attempt_limit: int = Field(default=2, ge=1, le=3)
    research_evidence_ttl_general_seconds: int = Field(default=86400, ge=60, le=604800)
    research_evidence_ttl_current_seconds: int = Field(default=3600, ge=60, le=86400)
    research_max_evidence_context_tokens: int = Field(default=4096, ge=1)
    research_timeout_seconds: float = Field(default=30, gt=0, le=120)
    research_provider_timeout_seconds: float = Field(default=10, gt=0, le=30)
    research_min_request_interval_seconds: float = Field(default=1, ge=1, le=60)
    iterative_research_enabled: bool = False
    iterative_progress_enabled: bool = False
    iterative_research_policy_version: str = Field(
        default="iterative-research-policy-v1", pattern=r"^iterative-research-policy-v1$"
    )
    iterative_max_iterations: int = Field(default=3, ge=1, le=5)
    iterative_max_queries: int = Field(default=3, ge=1, le=3)
    iterative_max_sources: int = Field(default=12, ge=1, le=12)
    iterative_max_elapsed_seconds: int = Field(default=90, ge=1, le=300)
    iterative_max_tokens: int = Field(default=16_000, ge=512, le=32_768)
    iterative_max_provider_cost_usd: Decimal = Field(
        default=Decimal("0.05"), ge=0, le=Decimal("1.00")
    )
    iterative_allowed_domains: tuple[str, ...] = Field(
        default=("example.org",), min_length=1, max_length=12
    )
    iterative_synthesis_reserve_tokens: int = Field(default=4096, ge=128, le=8192)
    iterative_synthesis_reserve_seconds: int = Field(default=20, ge=1, le=60)
    iterative_search_cost_usd: Decimal = Field(default=Decimal("0.005"), ge=0, le=Decimal("0.10"))
    iterative_synthesis_cost_usd: Decimal = Field(
        default=Decimal("0.005"), ge=0, le=Decimal("0.10")
    )

    travel_enabled: bool = False
    shopping_enabled: bool = False
    domain_inspection_enabled: bool = False
    domain_max_results: int = Field(default=8, ge=1, le=12)
    domain_max_comparison_rows: int = Field(default=12, ge=1, le=24)
    domain_max_response_bytes: int = Field(default=131072, ge=1024, le=262144)
    domain_provider_timeout_seconds: float = Field(default=10, gt=0, le=30)
    travel_places_adapter: str = Field(default="fake", pattern=r"^(fake|osm_nominatim)$")
    travel_provider_policy_approved: bool = False
    travel_osm_contact_email: str = Field(default="", max_length=254)
    travel_osm_user_agent: str = Field(default="PersonalAISystem/0.1", min_length=8, max_length=200)
    travel_min_request_interval_seconds: float = Field(default=1, ge=1, le=60)
    travel_place_ttl_seconds: int = Field(default=604800, ge=300, le=2592000)
    shopping_products_adapter: str = Field(default="fake", pattern=r"^(fake|open_food_facts)$")
    shopping_provider_policy_approved: bool = False
    shopping_off_user_agent: str = Field(default="", max_length=200)
    shopping_off_base_url: AnyHttpUrl = Field(default="https://world.openfoodfacts.net")
    shopping_min_request_interval_seconds: float = Field(default=4, ge=4, le=60)
    shopping_product_ttl_seconds: int = Field(default=2592000, ge=3600, le=7776000)

    decision_enabled: bool = False
    decision_inspection_enabled: bool = False
    entity_resolution_policy_version: str = Field(
        default="resolve-v2", min_length=1, max_length=100
    )
    entity_match_threshold: float = Field(default=0.9, ge=0, le=1)
    decision_constraint_policy_version: str = Field(
        default="constraint-v1", min_length=1, max_length=100
    )
    decision_ranking_policy_version: str = Field(default="rank-v1", min_length=1, max_length=100)
    decision_feature_preference_weight: float = Field(default=1.0, ge=0, le=1)
    decision_max_candidates: int = Field(default=12, ge=1, le=24)
    decision_max_comparison_rows: int = Field(default=12, ge=1, le=24)

    itinerary_proposals_enabled: bool = False
    itinerary_proposal_generator: str = Field(default="fake", pattern=r"^(fake|gemini)$")
    itinerary_proposal_provider_enabled: bool = False
    itinerary_proposal_storage: str = Field(default="postgres", pattern=r"^(postgres|memory)$")
    itinerary_proposal_timeout_seconds: float = Field(default=35, gt=0, le=45)
    itinerary_proposal_max_input_tokens: int = Field(default=4096, ge=512, le=32768)
    itinerary_proposal_max_output_tokens: int = Field(default=2048, ge=128, le=4096)
    itinerary_proposal_max_response_bytes: int = Field(default=32768, ge=1024, le=131072)

    booking_extractions_enabled: bool = False
    booking_extraction_generator: str = Field(default="fake", pattern=r"^(fake|gemini)$")
    booking_extraction_provider_enabled: bool = False
    booking_extraction_storage: str = Field(default="postgres", pattern=r"^(postgres|memory)$")
    booking_extraction_timeout_seconds: float = Field(default=30, gt=0, le=35)
    booking_extraction_max_input_tokens: int = Field(default=8192, ge=512, le=32768)
    booking_extraction_max_output_tokens: int = Field(default=2048, ge=128, le=4096)

    @model_validator(mode="after")
    def validate_context_budget(self) -> "Settings":
        for aliases in (self.groq_approved_model_aliases, self.cloudflare_approved_model_aliases):
            if (
                len(set(aliases)) != len(aliases)
                or any(not alias or alias != alias.strip() or len(alias) > 200 for alias in aliases)
            ):
                raise ValueError("provider_model_aliases_invalid")
        if self.groq_adapter_enabled and (
            not self.groq_model
            or not self.groq_api_key.get_secret_value()
            or not self.groq_free_tier_verified
            or not self.groq_privacy_approved
            or not self.groq_preflight_reference.strip()
        ):
            raise ValueError("groq_provider_preflight_required")
        if self.cloudflare_adapter_enabled and (
            not self.cloudflare_account_id
            or not self.cloudflare_model
            or not self.cloudflare_api_token.get_secret_value()
            or not self.cloudflare_free_tier_verified
            or not self.cloudflare_privacy_approved
            or not self.cloudflare_preflight_reference.strip()
        ):
            raise ValueError("cloudflare_provider_preflight_required")
        if self.p10_cloud_adapters_configured:
            if self.app_environment not in {"staging", "production"}:
                raise ValueError("p10_cloud_adapters_require_deployed_environment")
            from personal_ai.persistence.dynamodb_cloud import FederatedDynamoDBConfig
            from personal_ai.persistence.neon import NeonRuntimeDatabase

            dsn = self.p10_neon_runtime_dsn.get_secret_value()
            NeonRuntimeDatabase(
                dsn, environment=self.app_environment,
                max_size=self.p10_neon_pool_max_size,
            )
            FederatedDynamoDBConfig(
                region=self.p10_dynamodb_region,
                table_name=self.p10_dynamodb_table_name,
                role_arn=self.p10_dynamodb_role_arn,
                identity_token_audience=self.p10_dynamodb_identity_token_audience,
            ).validate()
        available = (
            self.max_context_tokens - self.max_response_tokens - self.context_safety_margin_tokens
        )
        if available <= 0 or self.max_summary_tokens >= available:
            raise ValueError("context_budget_invalid")
        if self.summary_trigger_tokens > available:
            raise ValueError("context_budget_invalid")
        for name in (
            "context_profile_max_tokens",
            "context_domain_max_tokens",
            "context_tool_max_tokens",
            "context_client_max_tokens",
        ):
            if name in self.model_fields_set and getattr(self, name) > available:
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
        if (
            any(not math.isfinite(weight) for weight in weights)
            or sum(weights) <= 0
            or self.memory_job_execution_seconds >= self.memory_job_lease_seconds
        ):
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
        if self.research_enabled and self.research_max_evidence_context_tokens > available:
            raise ValueError("research_configuration_invalid")
        if self.itinerary_proposals_enabled and (
            self.itinerary_proposal_max_input_tokens > available
            or self.itinerary_proposal_max_output_tokens > self.max_response_tokens
        ):
            raise ValueError("itinerary_proposal_configuration_invalid")
        if self.itinerary_proposal_provider_enabled and not self.itinerary_proposals_enabled:
            raise ValueError("itinerary_proposal_configuration_invalid")
        if self.booking_extractions_enabled and (
            self.booking_extraction_max_input_tokens > available
            or self.booking_extraction_max_output_tokens > self.max_response_tokens
        ):
            raise ValueError("booking_extraction_configuration_invalid")
        if self.booking_extraction_provider_enabled and not self.booking_extractions_enabled:
            raise ValueError("booking_extraction_configuration_invalid")
        if self.booking_extraction_generator == "gemini" and (
            not self.booking_extractions_enabled
            or not self.booking_extraction_provider_enabled
            or self.auth_mode != "google_oidc"
            or self.ai_provider.lower() != "gemini"
            or not self.ai_api_key.get_secret_value()
            or self.booking_extraction_storage != "postgres"
        ):
            raise ValueError("booking_extraction_configuration_invalid")
        if (
            self.booking_extractions_enabled
            and self.app_environment not in {"local", "test"}
            and (
                self.booking_extraction_generator != "gemini"
                or self.booking_extraction_storage != "postgres"
                or not self.booking_extraction_provider_enabled
            )
        ):
            raise ValueError("booking_extraction_configuration_invalid")
        if self.itinerary_proposal_generator == "gemini" and (
            not self.itinerary_proposals_enabled
            or not self.itinerary_proposal_provider_enabled
            or self.ai_provider.lower() != "gemini"
            or not self.ai_api_key.get_secret_value()
            or self.itinerary_proposal_storage != "postgres"
        ):
            raise ValueError("itinerary_proposal_configuration_invalid")
        if (
            self.itinerary_proposals_enabled
            and self.app_environment not in {"local", "test"}
            and (
                self.itinerary_proposal_generator != "gemini"
                or self.itinerary_proposal_storage != "postgres"
                or not self.itinerary_proposal_provider_enabled
            )
        ):
            raise ValueError("itinerary_proposal_configuration_invalid")
        if (
            self.itinerary_proposals_enabled
            and self.itinerary_proposal_storage == "memory"
            and self.app_environment not in {"local", "test"}
        ):
            raise ValueError("itinerary_proposal_configuration_invalid")
        if self.iterative_research_enabled and not self.research_enabled:
            raise ValueError("iterative_research_configuration_invalid")
        if (
            self.iterative_max_queries > 3
            or self.iterative_synthesis_reserve_tokens > self.iterative_max_tokens
            or self.iterative_synthesis_reserve_seconds > self.iterative_max_elapsed_seconds
            or self.iterative_synthesis_cost_usd > self.iterative_max_provider_cost_usd
        ):
            raise ValueError("iterative_research_configuration_invalid")
        domains = tuple(domain.lower().rstrip(".") for domain in self.iterative_allowed_domains)
        if (
            domains != self.iterative_allowed_domains
            or len(set(domains)) != len(domains)
            or any(not domain or "." not in domain or ".." in domain for domain in domains)
        ):
            raise ValueError("iterative_research_configuration_invalid")
        if (
            self.research_enabled
            and self.research_search_adapter == "brave"
            and (
                self.research_storage != "postgres"
                or not self.research_provider_storage_approved
                or not self.research_api_key.get_secret_value()
            )
        ):
            raise ValueError("research_configuration_invalid")
        decision_weights = (self.decision_feature_preference_weight,)
        domain_gates = (self.travel_enabled, self.shopping_enabled)
        if (
            self.entity_resolution_policy_version != "resolve-v2"
            or self.decision_constraint_policy_version != "constraint-v1"
            or self.decision_ranking_policy_version != "rank-v1"
            or any(not math.isfinite(weight) for weight in decision_weights)
            or self.decision_max_candidates > self.decision_max_comparison_rows
            or self.domain_max_comparison_rows < self.decision_max_candidates
            or any(domain_gates)
            and not self.decision_enabled
        ):
            raise ValueError("decision_configuration_invalid")
        if (
            self.travel_enabled
            and self.travel_places_adapter == "osm_nominatim"
            and (
                not self.travel_provider_policy_approved
                or not self.travel_osm_contact_email
                or "\r" in self.travel_osm_user_agent
                or "\n" in self.travel_osm_user_agent
            )
        ):
            raise ValueError("travel_configuration_invalid")
        if (
            self.shopping_enabled
            and self.shopping_products_adapter == "open_food_facts"
            and (
                not self.shopping_provider_policy_approved
                or not self.shopping_off_user_agent
                or self.shopping_off_base_url.scheme != "https"
                or self.shopping_off_base_url.host
                not in {
                    "world.openfoodfacts.net",
                    "world.openfoodfacts.org",
                }
            )
        ):
            raise ValueError("shopping_configuration_invalid")
        emails = self.auth_allowed_emails
        if self.app_environment not in {"local", "test"} and (
            self.auth_mode != "google_oidc"
            or not self.auth_required
            or not self.auth_audience
            or len(emails) != 1
        ):
            raise ValueError("authentication_configuration_invalid")
        if self.auth_mode == "development" and self.app_environment not in {"local", "test"}:
            raise ValueError("authentication_configuration_invalid")
        if self.auth_mode == "development" and self.auth_required:
            raise ValueError("authentication_configuration_invalid")
        if self.auth_mode == "google_oidc" and (
            not self.auth_required
            or not self.auth_audience
            or len(emails) != 1
            or any(
                not email
                or email != email.strip().lower()
                or email.count("@") != 1
                or any(char.isspace() for char in email)
                or "\r" in email
                or "\n" in email
                for email in emails
            )
            or self.auth_issuer not in {"accounts.google.com", "https://accounts.google.com"}
        ):
            raise ValueError("authentication_configuration_invalid")
        if self.auth_hosted_domain and (
            self.auth_hosted_domain != self.auth_hosted_domain.strip().lower()
            or "." not in self.auth_hosted_domain
            or any(not label or len(label) > 63 for label in self.auth_hosted_domain.split("."))
        ):
            raise ValueError("authentication_configuration_invalid")
        if self.auth_mode == "google_oidc" and any(
            email.rsplit("@", 1)[-1] != "gmail.com"
            and email.rsplit("@", 1)[-1] != self.auth_hosted_domain
            for email in emails
        ):
            raise ValueError("authentication_configuration_invalid")
        if len(set(emails)) != len(emails):
            raise ValueError("authentication_configuration_invalid")
        if self.app_environment in {"staging", "production"} and not self.allowed_origins:
            raise ValueError("authentication_configuration_invalid")
        for origin in self.allowed_origins:
            if (
                origin.username is not None
                or origin.password is not None
                or origin.path not in {None, "/"}
                or origin.query is not None
                or origin.fragment is not None
                or "*" in (origin.host or "")
                or self.app_environment in {"staging", "production"}
                and origin.scheme != "https"
            ):
                raise ValueError("authentication_configuration_invalid")
        return self

    allowed_origins: tuple[AnyHttpUrl, ...] = Field(
        default=(), validation_alias=AliasChoices("ALLOWED_ORIGINS", "CORS_ORIGINS")
    )

    @property
    def cors_origins(self) -> tuple[AnyHttpUrl, ...]:
        """Backward-compatible name for the explicit browser-origin allowlist."""
        return self.allowed_origins

    @property
    def allowed_web_origins(self) -> list[str]:
        """Return browser origins in the form expected by CORS middleware."""
        return [str(origin).rstrip("/") for origin in self.allowed_origins]


@lru_cache
def get_settings() -> Settings:
    """Provide a single settings instance for dependency injection."""
    try:
        return Settings()
    except ValidationError as error:
        if "context_budget_invalid" in str(error):
            raise ContextBudgetInvalidError("context_budget_invalid") from error
        raise


def validate_startup_configuration() -> None:
    """Fail startup when a deployed process lacks an explicit safe environment."""
    cloud_run_service = os.environ.get("K_SERVICE")
    environment = os.environ.get("APP_ENVIRONMENT")
    if cloud_run_service or environment in {"staging", "production"}:
        settings = get_settings()
        if cloud_run_service and settings.app_environment not in {"staging", "production"}:
            raise ValueError("deployed_environment_must_be_explicit")
        if not settings.p10_cloud_adapters_configured:
            raise ValueError("deployed_polyglot_persistence_required")
