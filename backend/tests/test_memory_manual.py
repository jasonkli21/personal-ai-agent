"""Opt-in synthetic checks; never run against real personal conversations."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from personal_ai.entities import Conversation, Message
from personal_ai.llm.memory import GeminiMemoryAdapter
from personal_ai.memory.contracts import MemoryCandidate
from personal_ai.memory.fake import FakeEmbedder, FakeMemoryExtractor
from personal_ai.memory.repositories import FirestoreMemoryRepository
from personal_ai.memory.services import MemoryExtractionService
from personal_ai.settings import Settings
from personal_ai.storage import FirestoreConversationRepository, FirestoreMessageRepository


@pytest.mark.skipif(
    os.environ.get("RUN_MEMORY_MANUAL_TEST") != "1", reason="Opt-in Gemini memory check"
)
def test_live_synthetic_embedding_and_extraction():
    settings = Settings(memory_enabled=True, memory_extraction_enabled=True)
    now, conversation_id = datetime.now(UTC), uuid4()
    user = Message(
        id=uuid4(),
        owner_id="local",
        conversation_id=conversation_id,
        role="user",
        content="I prefer quiet mountain cabins.",
        status="completed",
        created_at=now,
    )
    assistant = Message(
        id=uuid4(),
        owner_id="local",
        conversation_id=conversation_id,
        role="assistant",
        content="Understood.",
        status="completed",
        parent_message_id=user.id,
        created_at=now,
    )
    adapter = GeminiMemoryAdapter(settings)
    document = adapter.embed([user.content])[0]
    query = adapter.embed(["Which lodging atmosphere do I prefer?"], query=True)[0]
    assert len(document) == len(query) == settings.memory_embedding_dimensions
    candidates = adapter.extract([user, assistant], timeout=settings.memory_timeout_seconds)
    assert any(c.content == user.content and c.source_message_ids == (user.id,) for c in candidates)


@pytest.mark.skipif(
    os.environ.get("RUN_MEMORY_EMULATOR_TEST") != "1", reason="Opt-in memory emulator check"
)
def test_emulator_create_and_get_synthetic_memory():
    assert os.environ.get("FIRESTORE_EMULATOR_HOST"), "Explicit emulator environment is required"
    settings = Settings(
        memory_enabled=True,
        memory_extraction_enabled=True,
        memory_embedding_model="offline-synthetic",
        memory_embedding_dimensions=3,
    )
    conversations = FirestoreConversationRepository(
        project_id=settings.firestore_project_id, emulator_host=settings.firestore_emulator_host
    )
    messages = FirestoreMessageRepository(
        project_id=settings.firestore_project_id, emulator_host=settings.firestore_emulator_host
    )
    memories = FirestoreMemoryRepository(
        project_id=settings.firestore_project_id, emulator_host=settings.firestore_emulator_host
    )
    now = datetime.now(UTC)
    conversation = Conversation(
        id=uuid4(),
        owner_id="memory-manual-synthetic",
        title="Synthetic memory verification",
        created_at=now,
        updated_at=now,
    )
    conversations.create(conversation)
    user = Message(
        id=uuid4(),
        owner_id=conversation.owner_id,
        conversation_id=conversation.id,
        role="user",
        content="I prefer quiet mountain cabins.",
        status="completed",
        created_at=now,
    )
    assistant = Message(
        id=uuid4(),
        owner_id=conversation.owner_id,
        conversation_id=conversation.id,
        role="assistant",
        content="Understood.",
        status="completed",
        created_at=now,
        parent_message_id=user.id,
    )
    messages.create(user)
    messages.create(assistant)
    candidate = MemoryCandidate(
        memory_type="preference",
        content=user.content,
        confidence=1,
        source_message_ids=(user.id,),
        rationale_code="user_preference",
    )
    service = MemoryExtractionService(
        settings,
        memories,
        messages,
        FakeMemoryExtractor([candidate]),
        FakeEmbedder({user.content: [1, 0, 0]}),
    )
    result = service.run(assistant)
    assert len(result.created) == 1
    stored = memories.get(owner_id=conversation.owner_id, memory_id=result.created[0])
    assert stored.content == user.content and stored.source_message_ids == (user.id,)
    assert service.run(assistant).skipped == result.created


@pytest.mark.skipif(
    os.environ.get("RUN_MEMORY_TURN_MANUAL_TEST") != "1", reason="Opt-in end-to-end memory turn"
)
def test_live_synthetic_turn_persists_memory_and_retrieves_across_conversations():
    import asyncio

    from personal_ai.context import ContextAssembler
    from personal_ai.llm import GeminiLLMClient
    from personal_ai.llm.context import GeminiTokenCounter
    from personal_ai.memory.services import MemoryRetriever
    from personal_ai.services.chat_turns import ChatTurnService

    settings = Settings(memory_enabled=True, memory_extraction_enabled=True)
    assert settings.firestore_project_id, "Use a deliberate synthetic test project"
    conversations = FirestoreConversationRepository(
        project_id=settings.firestore_project_id, emulator_host=settings.firestore_emulator_host
    )
    messages = FirestoreMessageRepository(
        project_id=settings.firestore_project_id, emulator_host=settings.firestore_emulator_host
    )
    memories = FirestoreMemoryRepository(
        project_id=settings.firestore_project_id, emulator_host=settings.firestore_emulator_host
    )
    adapter = GeminiMemoryAdapter(settings)
    extraction = MemoryExtractionService(settings, memories, messages, adapter, adapter)
    outcomes = []

    class RecordingExtraction:
        def run(self, completed):
            result = extraction.run(completed)
            outcomes.append(result)
            return result

    owner = "memory-manual-" + str(uuid4())
    now = datetime.now(UTC)
    conversation = Conversation(
        id=uuid4(),
        owner_id=owner,
        title="Synthetic live memory turn",
        created_at=now,
        updated_at=now,
    )
    conversations.create(conversation)
    retriever = MemoryRetriever(settings, memories, messages, adapter)
    service = ChatTurnService(
        conversations,
        messages,
        GeminiLLMClient(settings),
        owner_id=owner,
        model=settings.ai_model,
        context_assembler=ContextAssembler(settings, GeminiTokenCounter(settings)),
        memory_retriever=retriever,
        memory_extraction=RecordingExtraction(),
    )

    async def consume():
        return [
            event
            async for event in service.send(
                conversation.id, "I prefer quiet mountain cabins.", request_id="synthetic-manual"
            )
        ]

    events = asyncio.run(consume())
    assert any(event.startswith("event: response.completed") for event in events)
    assert outcomes and len(outcomes[0].created) == 1
    memory = memories.get(owner_id=owner, memory_id=outcomes[0].created[0])
    assert memory.source_conversation_id == conversation.id and memory.source_message_ids
    # A query in a separate conversation has no raw source turn as context.
    later = Conversation(
        id=uuid4(), owner_id=owner, title="Synthetic later query", created_at=now, updated_at=now
    )
    conversations.create(later)
    user = Message(
        id=uuid4(),
        owner_id=owner,
        conversation_id=later.id,
        role="user",
        content="Which lodging atmosphere do I prefer?",
        status="completed",
        created_at=now,
    )
    messages.create(user)
    retrieved = retriever.retrieve(owner, user.content, [user])
    assert memory.id in [s.memory.id for s in retrieved.selected]
