"""Repository construction seam used by HTTP, worker, and control services.

Repositories use Postgres for query-rich knowledge and DynamoDB for operational
timeline state. Local/test environments require explicit local endpoints;
deployed environments require the configured Neon and federated AWS adapters.
"""

from __future__ import annotations

from hashlib import sha256
from threading import RLock
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from personal_ai.agents.research.iterative_repositories import IterativeResearchRepository
    from personal_ai.agents.research.repositories import ResearchRepository
    from personal_ai.auth.account_data import AccountDataRepository
    from personal_ai.auth.directory import PrincipalDirectory
    from personal_ai.auth.safeguards import SafeguardStore
    from personal_ai.booking_extractions.repositories import BookingExtractionRepository
    from personal_ai.context.contracts import ConversationSummaryRepository
    from personal_ai.decisions.repositories import DecisionRepository
    from personal_ai.domains.repositories import DomainRepository
    from personal_ai.itinerary_proposals.repositories import ItineraryProposalRepository
    from personal_ai.memory.contracts import MemoryRepository
    from personal_ai.memory.lifecycle import MemoryLifecycleRepository
    from personal_ai.storage.repositories import ConversationRepository, MessageRepository


class PersistenceFactory(Protocol):
    def conversation_repository(self) -> ConversationRepository: ...
    def message_repository(self) -> MessageRepository: ...
    def summary_repository(self) -> ConversationSummaryRepository: ...
    def memory_repository(self) -> MemoryRepository: ...
    def memory_lifecycle_repository(
        self, memories: MemoryRepository, messages: MessageRepository
    ) -> MemoryLifecycleRepository: ...
    def research_repository(self) -> ResearchRepository: ...
    def iterative_research_repository(self) -> IterativeResearchRepository: ...
    def decision_repository(self) -> DecisionRepository: ...
    def domain_repository(self) -> DomainRepository: ...
    def itinerary_proposal_repository(self) -> ItineraryProposalRepository: ...
    def booking_extraction_repository(self) -> BookingExtractionRepository: ...
    def principal_directory(self) -> PrincipalDirectory: ...
    def account_data_repository(self) -> AccountDataRepository: ...
    def safeguard_store(self) -> SafeguardStore: ...
    def provider_rate_limiter(self, provider: str, repository=None): ...


class PostgresDynamoPersistenceFactory:
    """Compose existing repository contracts over the two canonical stores."""

    def __init__(self, database, runtime_table) -> None:
        self.database = database
        self.runtime_table = runtime_table

    def conversation_repository(self):
        from personal_ai.persistence.dynamodb import DynamoDBConversationRepository

        return DynamoDBConversationRepository(self.runtime_table)

    def message_repository(self):
        from personal_ai.persistence.dynamodb import DynamoDBMessageRepository

        return DynamoDBMessageRepository(self.runtime_table, self.conversation_repository())

    def summary_repository(self):
        from personal_ai.persistence.dynamodb import DynamoDBSummaryRepository

        return DynamoDBSummaryRepository(self.runtime_table, self.conversation_repository())

    def memory_repository(self):
        from personal_ai.persistence.dynamodb import DynamoDBMemoryEffectGuard
        from personal_ai.persistence.postgres_memory import PostgresMemoryRepository

        return PostgresMemoryRepository(
            self.database,
            DynamoDBMemoryEffectGuard(self.runtime_table, self.message_repository()),
        )

    def memory_lifecycle_repository(self, memories, messages):
        from personal_ai.persistence.dynamodb import DynamoDBMemoryJobRepository
        from personal_ai.persistence.postgres_lifecycle import PostgresMemoryLifecycleRepository

        return PostgresMemoryLifecycleRepository(
            memories, messages, DynamoDBMemoryJobRepository(self.runtime_table)
        )

    def research_repository(self):
        from personal_ai.persistence.postgres_research import PostgresResearchRepository

        return PostgresResearchRepository(self.database)

    def iterative_research_repository(self):
        from personal_ai.persistence.postgres_research import (
            PostgresIterativeResearchRepository,
            PostgresResearchRepository,
        )

        return PostgresIterativeResearchRepository(
            self.database, PostgresResearchRepository(self.database)
        )

    def decision_repository(self):
        from personal_ai.persistence.postgres_decisions import PostgresDecisionRepository

        return PostgresDecisionRepository(self.database)

    def domain_repository(self):
        from personal_ai.persistence.postgres_domains import PostgresDomainRepository

        return PostgresDomainRepository(self.database)

    def itinerary_proposal_repository(self):
        from personal_ai.persistence.postgres_capabilities import (
            PostgresItineraryProposalRepository,
        )

        return PostgresItineraryProposalRepository(self.database)

    def booking_extraction_repository(self):
        from personal_ai.persistence.postgres_capabilities import (
            PostgresBookingExtractionRepository,
        )

        return PostgresBookingExtractionRepository(self.database)

    def principal_directory(self):
        from personal_ai.persistence.postgres_auth import PostgresPrincipalDirectory

        return PostgresPrincipalDirectory(self.database)

    def account_data_repository(self):
        from personal_ai.persistence.postgres_auth import PostgresAccountLifecycleRepository

        return PostgresAccountLifecycleRepository(self.database, self.runtime_table)

    def safeguard_store(self):
        from personal_ai.persistence.controls import (
            DynamoDBSafeguardStore,
            PostgresDailyBudgetRepository,
        )

        return DynamoDBSafeguardStore(
            self.runtime_table, PostgresDailyBudgetRepository(self.database)
        )

    def provider_rate_limiter(self, provider: str, repository=None):
        del repository
        from personal_ai.persistence.controls import PostgresDomainProviderRateLimiter

        return PostgresDomainProviderRateLimiter(self.database, provider)

    def close(self) -> None:
        self.database.close()
        close = getattr(self.runtime_table, "close", None)
        if close is not None:
            close()


_FACTORY_LOCK = RLock()
_FACTORIES: dict[tuple[str, ...], PostgresDynamoPersistenceFactory] = {}


def _factory_key(settings) -> tuple[str, ...]:
    cloud = settings.app_environment in {"staging", "production"}
    postgres_dsn = (
        settings.p10_neon_runtime_dsn.get_secret_value()
        if cloud else settings.persistence_local_postgres_dsn.get_secret_value()
    )
    postgres_key = sha256(postgres_dsn.encode()).hexdigest()
    endpoint = "cloud" if cloud else settings.persistence_local_dynamodb_endpoint
    return (
        settings.app_environment,
        str(cloud),
        postgres_key,
        endpoint,
        settings.p10_dynamodb_region,
        settings.p10_dynamodb_table_name,
        settings.p10_dynamodb_role_arn,
        settings.p10_dynamodb_identity_token_audience,
        str(settings.p10_neon_pool_max_size),
    )


def persistence_factory(settings) -> PersistenceFactory:
    """Return the configured runtime factory without cloud/local fallback."""
    cloud = settings.app_environment in {"staging", "production"}
    if cloud and not settings.p10_cloud_adapters_configured:
        raise RuntimeError("deployed_polyglot_persistence_required")
    if not cloud and settings.p10_cloud_adapters_configured:
        raise RuntimeError("cloud_persistence_requires_deployed_environment")

    key = _factory_key(settings)
    with _FACTORY_LOCK:
        factory = _FACTORIES.get(key)
        if factory is not None:
            return factory
        if cloud:
            from personal_ai.persistence.dynamodb_cloud import (
                FederatedDynamoDBConfig,
                FederatedDynamoDBRuntimeTable,
            )
            from personal_ai.persistence.neon import NeonRuntimeDatabase

            database = NeonRuntimeDatabase(
                settings.p10_neon_runtime_dsn.get_secret_value(),
                environment=settings.app_environment,
                max_size=settings.p10_neon_pool_max_size,
            )
            table = FederatedDynamoDBRuntimeTable(FederatedDynamoDBConfig(
                region=settings.p10_dynamodb_region,
                table_name=settings.p10_dynamodb_table_name,
                role_arn=settings.p10_dynamodb_role_arn,
                identity_token_audience=settings.p10_dynamodb_identity_token_audience,
            ))
        else:
            from personal_ai.persistence.dynamodb import DynamoDBRuntimeTable
            from personal_ai.persistence.postgres import PostgresDatabase

            database = PostgresDatabase(
                settings.persistence_local_postgres_dsn.get_secret_value(),
                environment=settings.app_environment,
            )
            table = DynamoDBRuntimeTable(
                settings.persistence_local_dynamodb_endpoint,
                table_name=settings.p10_dynamodb_table_name,
                region=settings.p10_dynamodb_region,
            )
        factory = PostgresDynamoPersistenceFactory(database, table)
        _FACTORIES[key] = factory
        return factory


def close_persistence_clients() -> None:
    """Close shared database clients during process shutdown."""
    with _FACTORY_LOCK:
        factories = tuple(_FACTORIES.values())
        _FACTORIES.clear()
    for factory in factories:
        factory.close()
