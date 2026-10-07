"""Repository construction seam used by HTTP, worker, and control services.

Application composition depends on this protocol. The current implementation
still selects Firestore until Phase 10 backfill/cutover; database SDK details
stay inside the selected factory and adapter modules.
"""

from __future__ import annotations

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


class FirestorePersistenceFactory:
    """The pre-cutover adapter factory; construction stays behind this seam."""

    def __init__(self, settings) -> None:
        self.settings = settings

    def conversation_repository(self):
        from personal_ai.storage import FirestoreConversationRepository

        return FirestoreConversationRepository(
            project_id=self.settings.firestore_project_id,
            emulator_host=self.settings.firestore_emulator_host,
        )

    def message_repository(self):
        from personal_ai.storage import FirestoreMessageRepository

        return FirestoreMessageRepository(
            project_id=self.settings.firestore_project_id,
            emulator_host=self.settings.firestore_emulator_host,
        )

    def summary_repository(self):
        from personal_ai.context.repositories import FirestoreSummaryRepository

        return FirestoreSummaryRepository(
            project_id=self.settings.firestore_project_id,
            emulator_host=self.settings.firestore_emulator_host,
        )

    def memory_repository(self):
        from personal_ai.memory.repositories import FirestoreMemoryRepository

        return FirestoreMemoryRepository(
            project_id=self.settings.firestore_project_id,
            emulator_host=self.settings.firestore_emulator_host,
        )

    def memory_lifecycle_repository(self, memories, messages):
        from personal_ai.memory.lifecycle_repositories import FirestoreMemoryLifecycleRepository

        return FirestoreMemoryLifecycleRepository(memories, messages)

    def research_repository(self):
        from personal_ai.agents.research.repositories import FirestoreResearchRepository

        return FirestoreResearchRepository(
            project_id=self.settings.firestore_project_id,
            emulator_host=self.settings.firestore_emulator_host,
        )

    def iterative_research_repository(self):
        from personal_ai.agents.research.iterative_repositories import (
            FirestoreIterativeResearchRepository,
        )

        return FirestoreIterativeResearchRepository(
            project_id=self.settings.firestore_project_id,
            emulator_host=self.settings.firestore_emulator_host,
        )

    def decision_repository(self):
        from personal_ai.decisions.firestore import FirestoreDecisionRepository

        return FirestoreDecisionRepository(
            project_id=self.settings.firestore_project_id,
            emulator_host=self.settings.firestore_emulator_host,
        )

    def domain_repository(self):
        from personal_ai.domains.repositories import FirestoreDomainRepository

        return FirestoreDomainRepository(
            project_id=self.settings.firestore_project_id,
            emulator_host=self.settings.firestore_emulator_host,
        )

    def itinerary_proposal_repository(self):
        from personal_ai.itinerary_proposals.repositories import (
            FirestoreItineraryProposalRepository,
        )

        return FirestoreItineraryProposalRepository(
            project_id=self.settings.firestore_project_id,
            emulator_host=self.settings.firestore_emulator_host,
        )

    def booking_extraction_repository(self):
        from personal_ai.booking_extractions.repositories import (
            FirestoreBookingExtractionRepository,
        )

        return FirestoreBookingExtractionRepository(
            project_id=self.settings.firestore_project_id,
            emulator_host=self.settings.firestore_emulator_host,
        )

    def principal_directory(self):
        from personal_ai.auth.directory import FirestorePrincipalDirectory

        return FirestorePrincipalDirectory(
            project_id=self.settings.firestore_project_id,
            emulator_host=self.settings.firestore_emulator_host,
        )

    def account_data_repository(self):
        from personal_ai.auth.account_data import FirestoreAccountDataRepository

        return FirestoreAccountDataRepository(
            project_id=self.settings.firestore_project_id,
            emulator_host=self.settings.firestore_emulator_host,
        )

    def safeguard_store(self):
        from personal_ai.auth.safeguards import FirestoreSafeguardStore

        return FirestoreSafeguardStore(
            project_id=self.settings.firestore_project_id,
            emulator_host=self.settings.firestore_emulator_host,
        )

    def provider_rate_limiter(self, provider: str, repository=None):
        from personal_ai.domains.providers import FirestoreProviderRateLimiter
        from personal_ai.storage.firestore import _firestore_client

        client = getattr(repository, "client", None)
        if client is None:
            client = _firestore_client(
                self.settings.firestore_project_id,
                self.settings.firestore_emulator_host,
            )
        return FirestoreProviderRateLimiter(client, provider)


class PostgresDynamoPersistenceFactory:
    """P10 repository composition for local/contract use before cutover.

    Construction is explicit so merely setting an application environment
    variable cannot silently move normal traffic away from Firestore.
    """

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

        return PostgresAccountLifecycleRepository(self.database)

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


def persistence_factory(settings) -> PersistenceFactory:
    """Return the single configured repository backend for this release."""
    return FirestorePersistenceFactory(settings)
