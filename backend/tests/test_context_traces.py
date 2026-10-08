from datetime import UTC, datetime, timedelta
from uuid import uuid4

from personal_ai.auth.scope import ApplicationScope
from personal_ai.context.builder import (
    ContextBuildItemReport,
    ContextBuildManifest,
    ContextBuildSourceFailureReport,
    ContextSourceBudgetReport,
)
from personal_ai.context.planner import ContextPlan
from personal_ai.context.providers import ContextSelection
from personal_ai.context.traces import (
    MAX_CONTEXT_TRACE_RETENTION,
    ContextTraceManifest,
    InMemoryContextTraceRepository,
)
from personal_ai.persistence.dynamodb import (
    DynamoDBContextTraceRepository,
    _namespace,
    _unmarshal,
)


def _trace(*, user_id=None, assistant_id=None, recorded_at=None, app="personal_ai", workspace=None):
    scope = ApplicationScope(application_id=app, workspace_id=workspace)
    manifest = ContextBuildManifest(
        counter_kind="estimated",
        counter_version="fake-counter-v1",
        global_input_tokens=400,
        actual_input_tokens=170,
        effective_sensitivity="sensitive",
        selected_message_ids=("selected-message",),
        excluded_messages=(("excluded-message", "summary_covered"),),
        items=(
            ContextBuildItemReport(
                source_class="global_profile",
                provider_id="global_profile",
                source_version="global-profile-v1:7",
                selected_operation="profile",
                source_id="private-source-value",
                item_id="private-item-value",
                authority="authoritative",
                sensitivity="sensitive",
                source_reference_count=1,
                injected=True,
                token_count=12,
            ),
            ContextBuildItemReport(
                source_class="external_research",
                provider_id="research",
                source_version="evidence-v1",
                selected_operation="search",
                source_id="private-excluded-source",
                item_id="private-excluded-item",
                authority="external",
                sensitivity="personal",
                source_reference_count=1,
                injected=False,
                token_count=30,
                omission_reason="source_budget",
            ),
        ),
        sources=(
            ContextSourceBudgetReport(
                source_class="global_profile",
                token_limit=100,
                token_count=12,
                counter_kind="estimated",
                injected_item_count=1,
                omitted_item_count=0,
            ),
        ),
        source_failures=(
            ContextBuildSourceFailureReport(
                provider_id="research", operation="search", reason="unavailable"
            ),
        ),
        planner_version="deterministic-context-planner-v1",
    )
    plan = ContextPlan(
        planner_version="deterministic-context-planner-v1",
        application_id=app,
        workspace_id=workspace,
        scope_fingerprint="a" * 64,
        selections=(
            ContextSelection(
                provider_id="global_profile",
                operation="profile",
                fields=("preferred_units",),
                max_results=1,
                max_bytes=2048,
                max_tokens=64,
            ),
        ),
    )
    return ContextTraceManifest.from_build(
        manifest,
        request_id="trace-request-1",
        conversation_id=uuid4(),
        user_message_id=user_id or uuid4(),
        assistant_message_id=assistant_id or uuid4(),
        scope=scope,
        recorded_at=recorded_at or datetime.now(UTC),
        context_plan=plan,
    )


def test_actual_trace_is_versioned_bounded_and_excludes_source_values():
    trace = _trace()
    encoded = trace.model_dump_json()

    assert trace.view_kind == "actual_build"
    assert trace.policy_version == "context-build-policy-v1"
    assert trace.planner_version == "deterministic-context-planner-v1"
    assert trace.requested_sources[0].provider_id == "global_profile"
    assert [item.disposition for item in trace.source_decisions] == ["selected", "omitted"]
    assert trace.source_decisions[0].authority == "authoritative"
    assert trace.source_decisions[1].reason == "source_budget"
    assert trace.provider_failures[0].reason == "unavailable"
    assert "private-source-value" not in encoded
    assert "private-item-value" not in encoded
    assert "private-excluded-source" not in encoded
    assert "private-excluded-item" not in encoded


def test_in_memory_trace_lookup_is_scoped_and_retains_only_recent_turns():
    repository = InMemoryContextTraceRepository()
    owner = "owner-a"
    first = _trace()
    for index in range(MAX_CONTEXT_TRACE_RETENTION + 1):
        repository.put(
            owner_id=owner,
            trace=first.model_copy(
                update={
                    "assistant_message_id": uuid4(),
                    "recorded_at": first.recorded_at + timedelta(seconds=index),
                }
            ),
        )

    assert len(next(iter(repository.records.values()))) == MAX_CONTEXT_TRACE_RETENTION
    assert repository.latest_for_user_turn(
        owner_id=owner,
        scope=ApplicationScope(),
        conversation_id=first.conversation_id,
        user_message_id=first.user_message_id,
    ) is not None
    assert repository.latest_for_user_turn(
        owner_id="owner-b",
        scope=ApplicationScope(),
        conversation_id=first.conversation_id,
        user_message_id=first.user_message_id,
    ) is None


class _MemoryRuntimeTable:
    def __init__(self):
        self.items = {}

    def get(self, key, *, consistent=True):
        del consistent
        return self.items.get((key["PK"], key["SK"]))

    def transact(self, operations):
        for operation in operations:
            if "Put" in operation:
                item = _unmarshal(operation["Put"]["Item"])
                self.items[(item["PK"], item["SK"])] = item
            elif "Update" in operation:
                action = operation["Update"]
                key = _unmarshal(action["Key"])
                values = _unmarshal(action["ExpressionAttributeValues"])
                item = self.items[(key["PK"], key["SK"])]
                item["sequence"] = values[":next"]
            elif "Delete" in operation:
                key = _unmarshal(operation["Delete"]["Key"])
                self.items.pop((key["PK"], key["SK"]), None)

    def query(self, *, partition, sort_prefix, descending, limit, **_kwargs):
        rows = [
            item for (pk, sk), item in self.items.items()
            if pk == partition and sk.startswith(sort_prefix)
        ]
        return sorted(rows, key=lambda item: item["SK"], reverse=descending)[:limit]


def test_dynamodb_trace_repository_keeps_scoped_records_and_bounded_retention():
    table = _MemoryRuntimeTable()
    repository = DynamoDBContextTraceRepository(table)
    base = _trace()
    scope = ApplicationScope(application_id=base.application_id, workspace_id=base.workspace_id)
    partition = f"{_namespace(scope, 'owner-a')}#CONV#{base.conversation_id}"
    table.items[(partition, "META")] = {
        "PK": partition,
        "SK": "META",
        "owner_id": "owner-a",
        "application_id": scope.application_id,
        "workspace_id_present": scope.workspace_id is not None,
        "workspace_id": scope.workspace_id or "",
    }

    for index in range(MAX_CONTEXT_TRACE_RETENTION + 2):
        repository.put(
            owner_id="owner-a",
            trace=base.model_copy(
                update={
                    "assistant_message_id": uuid4(),
                    "recorded_at": base.recorded_at + timedelta(seconds=index),
                }
            ),
        )

    retained = [item for item in table.items.values() if item.get("kind") == "context-trace"]
    assert len(retained) == MAX_CONTEXT_TRACE_RETENTION
    latest = repository.latest_for_user_turn(
        owner_id="owner-a",
        scope=ApplicationScope(),
        conversation_id=base.conversation_id,
        user_message_id=base.user_message_id,
    )
    assert latest is not None
    assert latest.request_id == base.request_id
    assert repository.latest_for_user_turn(
        owner_id="owner-b",
        scope=ApplicationScope(),
        conversation_id=base.conversation_id,
        user_message_id=base.user_message_id,
    ) is None
