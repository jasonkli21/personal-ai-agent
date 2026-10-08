"""Offline parity contract for Postgres lifecycle embedding-space discovery."""

from uuid import uuid4

from personal_ai.evaluation.memory import build_fixture, load_fixtures
from personal_ai.memory.contracts import Memory, ScoredMemory
from personal_ai.memory.fake import FakeMemoryExtractor
from personal_ai.memory.services import MemoryExtractionService
from personal_ai.persistence.postgres_lifecycle import PostgresMemoryLifecycleRepository


def _seeded_memory():
    fixture = next(item for item in load_fixtures() if item["name"] == "later-preference")
    settings, _, messages, memories, turns, candidates, _, embedder = build_fixture(fixture)
    settings.memory_enabled = True
    settings.memory_extraction_enabled = True
    result = MemoryExtractionService(
        settings, memories, messages, FakeMemoryExtractor([candidates[0]]), embedder
    ).run(turns[0][1])
    return messages, memories.get(owner_id="local", memory_id=result.created[0])


class _RecordingMemories:
    database = object()

    def __init__(self, anchor, results):
        self.anchor = anchor
        self.results = results
        self.search_args = None

    def get(self, *, owner_id, memory_id):
        assert owner_id == self.anchor.owner_id
        assert memory_id == self.anchor.id
        return self.anchor

    def search(self, **kwargs):
        self.search_args = kwargs
        return self.results


def test_postgres_lifecycle_discovery_forwards_full_embedding_identity_and_filters_results(
    monkeypatch,
):
    messages, base = _seeded_memory()
    anchor = base.model_copy(
        update={"embedding_provider": "synthetic-provider", "embedding_space_version": "v9"}
    )
    incompatible = base.model_copy(update={"embedding_provider": "other-provider"})
    compatible = base.model_copy(
        update={
            "id": uuid4(),
            "embedding_provider": "synthetic-provider",
            "embedding_space_version": "v9",
        }
    )
    memories = _RecordingMemories(
        anchor,
        (ScoredMemory(incompatible, 0.9), ScoredMemory(compatible, 0.8)),
    )
    lifecycle = PostgresMemoryLifecycleRepository(memories, messages, jobs=None)
    monkeypatch.setattr(lifecycle, "_source_is_valid", lambda owner_id, record: True)

    related = lifecycle.discover_related(owner_id=anchor.owner_id, memory_id=anchor.id, limit=3)

    assert related == (anchor.id, compatible.id)
    assert {
        key: memories.search_args[key]
        for key in (
            "provider",
            "model",
            "dimensions",
            "normalization",
            "document_task",
            "query_task",
            "embedding_space_version",
        )
    } == {
        "provider": "synthetic-provider",
        "model": anchor.embedding_model,
        "dimensions": anchor.embedding_dimensions,
        "normalization": anchor.embedding_normalization,
        "document_task": anchor.embedding_document_task,
        "query_task": anchor.embedding_query_task,
        "embedding_space_version": "v9",
    }


def test_legacy_memory_payload_defaults_to_v1_for_lifecycle_discovery(monkeypatch):
    messages, base = _seeded_memory()
    legacy_payload = base.model_dump()
    legacy_payload.pop("embedding_space_version")
    anchor = Memory.model_validate(legacy_payload)
    compatible = base.model_copy(update={"id": uuid4(), "embedding_space_version": "v1"})
    incompatible = base.model_copy(update={"embedding_space_version": "v2"})
    memories = _RecordingMemories(
        anchor,
        (ScoredMemory(incompatible, 0.9), ScoredMemory(compatible, 0.8)),
    )
    lifecycle = PostgresMemoryLifecycleRepository(memories, messages, jobs=None)
    monkeypatch.setattr(lifecycle, "_source_is_valid", lambda owner_id, record: True)

    related = lifecycle.discover_related(owner_id=anchor.owner_id, memory_id=anchor.id, limit=3)

    assert anchor.embedding_space_version == "v1"
    assert related == (anchor.id, compatible.id)
    assert memories.search_args["embedding_space_version"] == "v1"
