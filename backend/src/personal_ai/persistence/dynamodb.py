"""Access-pattern-first DynamoDB Local repositories for runtime timeline state."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

from personal_ai.auth.scope import (
    ApplicationScope,
    current_application_scope,
    scope_matches,
    scoped_record,
)
from personal_ai.context.contracts import ConversationSummary, fingerprint
from personal_ai.context.repositories import newest_compatible
from personal_ai.entities import Conversation, Message, MessageRole, MessageStatus
from personal_ai.persistence.postgres_memory import EffectGuardToken
from personal_ai.storage.branches import active_path, descendant_ids, effective_message
from personal_ai.storage.errors import (
    ConversationConflictError,
    ResourceNotFoundError,
    StorageUnavailableError,
)

RUNTIME_TABLE_NAME = "personal-ai-runtime-v1"
MAX_DYNAMO_ITEM_BYTES = 400 * 1024
MAX_DYNAMO_TRANSACTION_ITEMS = 100
MAX_DYNAMO_TRANSACTION_BYTES = 4 * 1024 * 1024
SUMMARY_CHUNK_IDS = 256
MAX_SUMMARY_CHUNKS = 200
MAX_CONVERSATION_MESSAGES = 10_000


class DynamoDBLocalClient:
    """Explicit-endpoint Dynamo client that cannot fall back to AWS credentials."""

    def __init__(self, endpoint_url: str, *, region: str = "us-east-1", client=None) -> None:
        from urllib.parse import urlsplit

        parsed = urlsplit(endpoint_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1", "dynamodb-local", "dynamodb-local-test"}
            or not parsed.port
        ):
            raise ValueError("dynamodb_local_endpoint_invalid")
        if client is not None:
            self.client = client
            self.endpoint_url = endpoint_url
            return
        try:
            import boto3
            from botocore.config import Config
        except ImportError as error:  # pragma: no cover - packaging failure
            raise RuntimeError("boto3_required") from error
        self.endpoint_url = endpoint_url
        self.client = boto3.client(
            "dynamodb",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id="fakeMyKeyId",
            aws_secret_access_key="fakeSecretAccessKey",
            config=Config(
                connect_timeout=2,
                read_timeout=5,
                retries={"mode": "standard", "max_attempts": 2},
                tcp_keepalive=True,
            ),
        )

    def ensure_runtime_table(self, table_name: str = RUNTIME_TABLE_NAME) -> None:
        from botocore.exceptions import ClientError

        try:
            self.client.describe_table(TableName=table_name)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                raise StorageUnavailableError("dynamodb_local_unavailable") from error
            self.client.create_table(
                TableName=table_name,
                AttributeDefinitions=[
                    {"AttributeName": "PK", "AttributeType": "S"},
                    {"AttributeName": "SK", "AttributeType": "S"},
                    {"AttributeName": "PUBPK", "AttributeType": "S"},
                    {"AttributeName": "PUBSK", "AttributeType": "S"},
                ],
                KeySchema=[
                    {"AttributeName": "PK", "KeyType": "HASH"},
                    {"AttributeName": "SK", "KeyType": "RANGE"},
                ],
                GlobalSecondaryIndexes=[
                    {
                        "IndexName": "job-publication-v1",
                        "KeySchema": [
                            {"AttributeName": "PUBPK", "KeyType": "HASH"},
                            {"AttributeName": "PUBSK", "KeyType": "RANGE"},
                        ],
                        "Projection": {
                            "ProjectionType": "INCLUDE",
                            "NonKeyAttributes": [
                                "record_pk",
                                "record_sk",
                                "revision",
                                "created_at",
                                "publish_after",
                                "job_id",
                            ],
                        },
                    }
                ],
                BillingMode="PAY_PER_REQUEST",
            )
        waiter = self.client.get_waiter("table_exists")
        waiter.wait(TableName=table_name, WaiterConfig={"Delay": 1, "MaxAttempts": 30})


class DynamoDBRuntimeTable:
    """Small SDK boundary shared by the runtime repositories."""

    def __init__(
        self,
        endpoint_url: str,
        *,
        table_name: str = RUNTIME_TABLE_NAME,
        region: str = "us-east-1",
        client=None,
    ) -> None:
        self.local = DynamoDBLocalClient(endpoint_url, region=region, client=client)
        self.client = self.local.client
        self.table_name = table_name

    def bootstrap(self) -> None:
        self.local.ensure_runtime_table(self.table_name)

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if close is not None:
            close()

    def get(self, key: dict[str, str], *, consistent: bool = True) -> dict[str, Any] | None:
        response = self.client.get_item(
            TableName=self.table_name,
            Key=_marshal(key),
            ConsistentRead=consistent,
        )
        item = response.get("Item")
        return None if item is None else _unmarshal(item)

    def query(
        self,
        *,
        partition: str,
        sort_prefix: str,
        consistent: bool = True,
        descending: bool = False,
        deadline: float,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        cursor = None
        while True:
            if monotonic() >= deadline:
                raise TimeoutError("dynamodb query deadline")
            request: dict[str, Any] = {
                "TableName": self.table_name,
                "KeyConditionExpression": "#pk = :pk AND begins_with(#sk, :prefix)",
                "ExpressionAttributeNames": {"#pk": "PK", "#sk": "SK"},
                "ExpressionAttributeValues": _marshal({":pk": partition, ":prefix": sort_prefix}),
                "ConsistentRead": consistent,
                "ScanIndexForward": not descending,
                "Limit": min(100, limit - len(result)) if limit is not None else 100,
            }
            if cursor is not None:
                request["ExclusiveStartKey"] = _marshal(cursor)
            page = self.client.query(**request)
            result.extend(_unmarshal(item) for item in page.get("Items", ()))
            if limit is not None and len(result) >= limit:
                break
            cursor = _unmarshal(page["LastEvaluatedKey"]) if page.get("LastEvaluatedKey") else None
            if not cursor:
                break
        return result

    def transact(self, operations: list[dict[str, Any]]) -> None:
        if not operations or len(operations) > MAX_DYNAMO_TRANSACTION_ITEMS:
            raise StorageUnavailableError("dynamodb transaction item bound exceeded")
        total = sum(_operation_size(operation) for operation in operations)
        if total > MAX_DYNAMO_TRANSACTION_BYTES:
            raise StorageUnavailableError("dynamodb transaction byte bound exceeded")
        for operation in operations:
            action = next(iter(operation.values()))
            action["TableName"] = self.table_name
        self.client.transact_write_items(TransactItems=operations)


class DynamoDBConversationRepository:
    """Strongly visible owner/app/workspace conversation directory and metadata."""

    def __init__(self, table: DynamoDBRuntimeTable) -> None:
        self.table = table

    def create(self, conversation: Conversation) -> Conversation:
        conversation = scoped_record(conversation)
        if conversation.context_preparation_id is not None:
            raise ValueError("conversation_initialization_invalid")
        scope = _scope_of(conversation)
        payload = _conversation_payload(conversation)
        catalog = _catalog_item(conversation, revision=1)
        operations = [
            _put(_metadata_item(conversation, payload, revision=1)),
            _put(catalog, condition="attribute_not_exists(PK)"),
        ]
        for attempt in range(2):
            scoped_operations = list(operations)
            scoped_operations.extend(_namespace_puts(self.table, conversation.owner_id, scope))
            try:
                self.table.transact(scoped_operations)
                break
            except Exception as error:
                existing = self._metadata_item_for(conversation.owner_id, conversation.id, scope)
                if existing is not None:
                    raise ConversationConflictError("conversation already exists") from error
                if attempt or not _conditional_failure(error):
                    raise
        return conversation.model_copy(update={"persistence_revision": 1})

    def get(self, *, owner_id: str, conversation_id: UUID) -> Conversation:
        scope = current_application_scope()
        return self._read_conversation(owner_id, conversation_id, scope)

    def list(self, *, owner_id: str, limit: int = 50) -> list[Conversation]:
        if limit < 1:
            return []
        if limit > 500:
            raise ValueError("conversation_limit_invalid")
        scope = current_application_scope()
        token = _namespace(scope, owner_id)
        catalog_pk = f"{token}#CATALOG"
        deadline = monotonic() + 5
        entries = self.table.query(
            partition=catalog_pk,
            sort_prefix="CONV#",
            descending=True,
            deadline=deadline,
            limit=min(limit, 500),
        )
        conversations = []
        for entry in entries:
            identifier = UUID(entry["conversation_id"])
            current = self._metadata_item_for(owner_id, identifier, scope)
            if current is None or int(current["revision"]) != int(entry["revision"]):
                raise StorageUnavailableError("conversation directory revision mismatch")
            conversation = self._read_conversation(owner_id, identifier, scope)
            if _timestamp(conversation.updated_at) != entry["updated_at"]:
                # Directory movement is part of the conversation transaction.
                # A mismatch signals an invariant breach instead of a stale page.
                raise StorageUnavailableError("conversation directory revision mismatch")
            conversations.append(conversation)
        return conversations

    def update(self, conversation: Conversation) -> Conversation:
        conversation = scoped_record(conversation)
        scope = _scope_of(conversation)
        if conversation.persistence_revision < 1:
            raise ConversationConflictError("conversation revision missing")
        old_item = self._metadata_item_for(conversation.owner_id, conversation.id, scope)
        if old_item is None:
            raise ResourceNotFoundError("conversation not found")
        if int(old_item["revision"]) != conversation.persistence_revision:
            raise ConversationConflictError("conversation changed")
        old = _conversation_from_item(old_item)
        self._write_conversation(old, conversation)
        return conversation.model_copy(update={"persistence_revision": old.persistence_revision + 1})

    def touch(self, *, owner_id: str, conversation_id: UUID, updated_at: datetime) -> Conversation:
        current = self.get(owner_id=owner_id, conversation_id=conversation_id)
        updated = current.model_copy(update={"updated_at": _utc(updated_at)})
        self._write_conversation(current, updated)
        return updated.model_copy(update={"persistence_revision": current.persistence_revision + 1})

    def _read_conversation(self, owner_id: str, conversation_id: UUID, scope: ApplicationScope):
        item = self._metadata_item_for(owner_id, conversation_id, scope)
        if item is None:
            raise ResourceNotFoundError("conversation not found")
        try:
            return _conversation_from_item(item)
        except (ValueError, TypeError, KeyError) as error:
            raise StorageUnavailableError("conversation record invalid") from error

    def _metadata_item_for(self, owner_id: str, conversation_id: UUID, scope: ApplicationScope):
        keys = _conversation_keys(scope, conversation_id, owner_id)
        item = self.table.get(keys.meta)
        if item is None or not _authorized(item, owner_id, scope):
            return None
        return item

    def _write_conversation(self, previous: Conversation, updated: Conversation) -> None:
        scope = _scope_of(previous)
        keys = _conversation_keys(scope, previous.id, previous.owner_id)
        current_item = self.table.get(keys.meta)
        if current_item is None or not _authorized(current_item, previous.owner_id, scope):
            raise ResourceNotFoundError("conversation not found")
        old_revision = int(current_item["revision"])
        if old_revision != previous.persistence_revision:
            raise ConversationConflictError("conversation changed")
        old_catalog = _catalog_key(scope, previous.id, previous.updated_at, previous.owner_id)
        new_catalog = _catalog_item(updated, revision=old_revision + 1)
        payload = _conversation_payload(updated)
        operations = [
            _update(
                keys.meta,
                update_expression="SET #payload=:payload,#updated=:updated,#revision=:next",
                names={"#payload": "payload", "#updated": "updated_at", "#revision": "revision"},
                values={
                    ":payload": _json(payload),
                    ":updated": _timestamp(updated.updated_at),
                    ":next": old_revision + 1,
                    ":owner": previous.owner_id,
                    ":app": scope.application_id,
                    ":workspace_present": scope.workspace_id is not None,
                    ":workspace": scope.workspace_id or "",
                },
                condition="#owner=:owner AND #app=:app AND revision=:old AND attribute_not_exists(effect_guard)",
                more_names={
                    "#owner": "owner_id", "#app": "application_id",
                    "#workspace_present": "workspace_id_present", "#workspace": "workspace_id",
                },
                more_values={":old": old_revision},
            )
        ]
        operations[0]["Update"]["ConditionExpression"] += (
            " AND #workspace_present=:workspace_present AND #workspace=:workspace"
        )
        new_catalog_key = {"PK": new_catalog["PK"], "SK": new_catalog["SK"]}
        if old_catalog != new_catalog_key:
            operations.extend(
                [
                    _delete(old_catalog),
                    _put(new_catalog, condition="attribute_not_exists(PK)"),
                ]
            )
        else:
            operations.append(_update(
                old_catalog,
                "SET #revision=:revision,#updated=:updated",
                names={"#revision": "revision", "#updated": "updated_at", "#owner": "owner_id"},
                values={":revision": old_revision + 1, ":updated": _timestamp(updated.updated_at),
                        ":owner": previous.owner_id},
                condition="#owner=:owner",
            ))
        self.table.transact(operations)


class DynamoDBMessageRepository:
    """Append-only history with revision-stable strong pagination and bounded cuts."""

    def __init__(self, table: DynamoDBRuntimeTable, conversations: DynamoDBConversationRepository | None = None):
        self.table = table
        self.conversations = conversations or DynamoDBConversationRepository(table)

    def create(self, message: Message) -> Message:
        message = scoped_record(message)
        scope = _scope_of(message)
        conversation = self.conversations.get(
            owner_id=message.owner_id, conversation_id=message.conversation_id
        )
        key = _conversation_keys(scope, message.conversation_id, message.owner_id)
        meta = self.table.get(key.meta)
        if meta is None:
            raise ResourceNotFoundError("conversation not found")
        revision = int(meta["revision"])
        current_updated = conversation.updated_at
        updated = conversation.model_copy(update={"updated_at": message.created_at})
        item = _message_item(message, scope)
        operations = [
            _put(item, condition="attribute_not_exists(PK)"),
            _put(_message_locator(message, scope), condition="attribute_not_exists(PK)"),
            _update(
                key.meta,
                update_expression="SET #payload=:payload,#updated=:updated,#revision=:next",
                names={"#payload": "payload", "#updated": "updated_at", "#revision": "revision",
                       "#owner": "owner_id"},
                values={":payload": _json(_conversation_payload(updated)),
                        ":updated": _timestamp(updated.updated_at), ":next": revision + 1,
                        ":owner": message.owner_id, ":old": revision},
                condition="#owner=:owner AND revision=:old AND attribute_not_exists(effect_guard) "
                          "AND attribute_not_exists(context_preparation_id)",
            ),
        ]
        old_catalog = _catalog_key(scope, conversation.id, current_updated, message.owner_id)
        new_catalog = _catalog_item(updated, revision=revision + 1)
        if old_catalog != {"PK": new_catalog["PK"], "SK": new_catalog["SK"]}:
            operations.extend([_delete(old_catalog), _put(new_catalog, condition="attribute_not_exists(PK)")])
        else:
            operations.append(_update(
                old_catalog,
                "SET #revision=:revision,#updated=:updated",
                names={"#revision": "revision", "#updated": "updated_at", "#owner": "owner_id"},
                values={":revision": revision + 1, ":updated": _timestamp(updated.updated_at),
                        ":owner": message.owner_id},
                condition="#owner=:owner",
            ))
        self.table.transact(operations)
        return message

    def get(self, *, owner_id: str, conversation_id: UUID, message_id: UUID) -> Message:
        scope = current_application_scope()
        keys = _conversation_keys(scope, conversation_id, owner_id)
        deadline = monotonic() + 5
        for _ in range(4):
            before = self.conversations._metadata_item_for(owner_id, conversation_id, scope)
            if before is None:
                raise ResourceNotFoundError("conversation not found")
            locator = self.table.get({"PK": keys.partition, "SK": f"MID#{message_id}"})
            if locator is None or not _authorized(locator, owner_id, scope):
                raise ResourceNotFoundError("message not found")
            item = self.table.get({"PK": locator["message_pk"], "SK": locator["message_sk"]})
            if (
                item is None
                or item.get("conversation_id") != str(conversation_id)
                or not _authorized(item, owner_id, scope)
            ):
                raise ResourceNotFoundError("message not found")
            message = _message_from_item(item)
            history = self._read_history(
                owner_id, conversation_id, scope, deadline=deadline
            )
            if len(history) > MAX_CONVERSATION_MESSAGES:
                raise StorageUnavailableError("conversation history exceeds bound")
            ancestry = {record.id: record for record in history}
            if message.id not in ancestry:
                raise StorageUnavailableError("message ancestry unavailable")
            after = self.conversations._metadata_item_for(owner_id, conversation_id, scope)
            if after is None:
                raise ResourceNotFoundError("conversation not found")
            if before["revision"] == after["revision"]:
                return effective_message(ancestry[message.id], ancestry)
            if monotonic() >= deadline:
                break
        raise StorageUnavailableError("conversation changed during message read")

    def list_active(
        self, *, owner_id: str, conversation_id: UUID, timeout: float | None = None
    ) -> list[Message]:
        scope = current_application_scope()
        deadline = monotonic() + (timeout if timeout is not None else 5)
        for _ in range(4):
            before = self.conversations._metadata_item_for(owner_id, conversation_id, scope)
            if before is None:
                raise ResourceNotFoundError("conversation not found")
            history = self._read_history(owner_id, conversation_id, scope, deadline=deadline)
            after = self.conversations._metadata_item_for(owner_id, conversation_id, scope)
            if after is None:
                raise ResourceNotFoundError("conversation not found")
            if before["revision"] == after["revision"]:
                return active_path(history)
            if monotonic() >= deadline:
                break
        raise StorageUnavailableError("conversation changed during history read")

    def update_status(
        self,
        *,
        owner_id: str,
        conversation_id: UUID,
        message_id: UUID,
        status: MessageStatus,
        content: str | None = None,
        model: str | None = None,
        error_code: str | None = None,
        updated_at: datetime,
        expected_status: MessageStatus | None = None,
    ) -> Message | None:
        current = self.get(owner_id=owner_id, conversation_id=conversation_id, message_id=message_id)
        if expected_status is not None and current.status is not expected_status:
            return None
        changes = {"status": status.value}
        if content is not None:
            changes["content"] = content
        if model is not None:
            changes["model"] = model
        if error_code is not None:
            changes["error_code"] = error_code
        updated = current.model_copy(update={"status": status, **{k: v for k, v in changes.items() if k != "status"}})
        scope = _scope_of(current)
        conversation = self.conversations.get(owner_id=owner_id, conversation_id=conversation_id)
        meta_key = _conversation_keys(scope, conversation_id, owner_id).meta
        metadata = self.table.get(meta_key)
        if metadata is None:
            raise ResourceNotFoundError("conversation not found")
        revision = int(metadata["revision"])
        updated_conversation = conversation.model_copy(update={"updated_at": _utc(updated_at)})
        message_key = _message_key(scope, conversation_id, current.created_at, current.id, owner_id)
        names = {"#status": "status", "#owner": "owner_id", "#payload": "payload"}
        message_values: dict[str, Any] = {":status": status.value, ":owner": owner_id,
                                          ":message_payload": _json(_message_payload(updated))}
        message_expression = "SET #status=:status,#payload=:message_payload"
        condition = "#owner=:owner"
        if expected_status is not None:
            condition += " AND #status=:expected"
            message_values[":expected"] = expected_status.value
        operations = [
            _update(message_key, message_expression, names=names, values=message_values, condition=condition),
            _update(meta_key,
                    "SET #payload=:conversation_payload,#updated=:updated,#revision=:next",
                    names={"#payload": "payload", "#updated": "updated_at", "#revision": "revision",
                           "#owner": "owner_id"},
                    values={":conversation_payload": _json(_conversation_payload(updated_conversation)),
                            ":updated": _timestamp(updated_at), ":next": revision + 1, ":owner": owner_id,
                            ":revision": revision},
                    condition="#owner=:owner AND revision=:revision AND attribute_not_exists(effect_guard)"),
        ]
        self._append_catalog_move(operations, scope, conversation, updated_conversation, revision + 1)
        try:
            self.table.transact(operations)
        except Exception as error:
            if _conditional_failure(error) and expected_status is not None:
                return None
            if _conditional_failure(error):
                raise ConversationConflictError("conversation changed") from error
            raise
        return updated

    def prepare_message_turn(
        self,
        *,
        owner_id: str,
        conversation_id: UUID,
        expected_active_ids: Sequence[UUID],
        supersede_from_message_id: UUID | None,
        messages: Sequence[Message],
        updated_at: datetime,
        preparation_id: UUID | None = None,
        complete_preparation: bool = False,
    ) -> list[Message]:
        scope = current_application_scope()
        messages = tuple(scoped_record(item) for item in messages)
        deadline = monotonic() + 5
        metadata = self.conversations._metadata_item_for(owner_id, conversation_id, scope)
        if metadata is None:
            raise ResourceNotFoundError("conversation not found")
        revision = int(metadata["revision"])
        history = self._read_history(owner_id, conversation_id, scope, deadline=deadline)
        stable = self.conversations._metadata_item_for(owner_id, conversation_id, scope)
        if stable is None or int(stable["revision"]) != revision:
            raise ConversationConflictError("conversation changed; retry the request")
        lease = metadata.get("context_preparation_id")
        if complete_preparation and lease != str(preparation_id):
            raise ConversationConflictError("context preparation expired")
        if not complete_preparation and lease is not None:
            raise ConversationConflictError("context preparation is in progress")
        if metadata.get("effect_guard") is not None:
            raise ConversationConflictError("memory effect is being applied")
        active = active_path(history)
        if [item.id for item in active] != list(expected_active_ids):
            raise ConversationConflictError("conversation changed; retry the request")
        if any(item.status is MessageStatus.STREAMING for item in active):
            raise ConversationConflictError("a response is already in progress")
        if supersede_from_message_id is not None and supersede_from_message_id not in {item.id for item in active}:
            raise ConversationConflictError("retry target is no longer active")
        history_ids = {item.id for item in history}
        if any(item.id in history_ids for item in messages):
            raise ConversationConflictError("message already exists")
        if any(item.owner_id != owner_id or item.conversation_id != conversation_id for item in messages):
            raise ResourceNotFoundError("conversation not found")
        conversation = _conversation_from_item(metadata)
        updated_conversation = conversation.model_copy(update={"updated_at": _utc(updated_at)})
        next_revision = revision + 1
        operations: list[dict[str, Any]] = []
        if supersede_from_message_id is not None:
            target = next((item for item in history if item.id == supersede_from_message_id), None)
            if target is None:
                raise ConversationConflictError("retry target is no longer active")
            operations.append(_update(
                _message_key(scope, conversation_id, target.created_at, target.id, owner_id),
                "SET #status=:status,#payload=:payload",
                names={"#status": "status", "#owner": "owner_id", "#payload": "payload"},
                values={":status": MessageStatus.SUPERSEDED.value, ":owner": owner_id,
                        ":payload": _json(_message_payload(target.model_copy(update={"status": MessageStatus.SUPERSEDED})))},
                condition="#owner=:owner AND #status <> :status",
            ))
        for message in messages:
            canonical = _message_item(message, scope)
            locator = _message_locator(message, scope)
            operations.extend([
                _put(canonical, condition="attribute_not_exists(PK)"),
                _put(locator, condition="attribute_not_exists(PK)"),
            ])
        update_expression = "SET #payload=:payload,#updated=:updated,#revision=:next"
        names = {"#payload": "payload", "#updated": "updated_at", "#revision": "revision",
                 "#owner": "owner_id"}
        values: dict[str, Any] = {":payload": _json(_conversation_payload(updated_conversation)),
                                  ":updated": _timestamp(updated_at), ":next": next_revision,
                                  ":owner": owner_id, ":revision": revision}
        condition = "#owner=:owner AND revision=:revision AND attribute_not_exists(effect_guard)"
        if complete_preparation:
            condition += " AND context_preparation_id=:preparation"
            values[":preparation"] = str(preparation_id)
            update_expression += " REMOVE context_preparation_id,context_preparation_started_at"
        elif preparation_id is not None:
            condition += " AND attribute_not_exists(context_preparation_id)"
            update_expression = (
                "SET #payload=:payload,#updated=:updated,#revision=:next,"
                "context_preparation_id=:preparation,context_preparation_started_at=:started"
            )
            values[":preparation"] = str(preparation_id)
            values[":started"] = _timestamp(updated_at)
        operations.append(_update(
            _conversation_keys(scope, conversation_id, owner_id).meta,
            update_expression,
            names=names,
            values=values,
            condition=condition,
        ))
        self._append_catalog_move(operations, scope, conversation, updated_conversation, next_revision)
        try:
            self.table.transact(operations)
        except Exception as error:
            if _conditional_failure(error):
                raise ConversationConflictError("conversation changed; retry the request") from error
            raise
        return list(messages)

    def release_preparation(self, *, owner_id: str, conversation_id: UUID, preparation_id: UUID) -> None:
        scope = current_application_scope()
        metadata = self.conversations._metadata_item_for(owner_id, conversation_id, scope)
        if metadata is None:
            raise ResourceNotFoundError("conversation not found")
        try:
            self.table.transact([
                _update(
                    _conversation_keys(scope, conversation_id, owner_id).meta,
                    "REMOVE context_preparation_id,context_preparation_started_at",
                    names={"#owner": "owner_id"},
                    values={":owner": owner_id, ":preparation": str(preparation_id)},
                    condition="#owner=:owner AND context_preparation_id=:preparation "
                              "AND attribute_not_exists(effect_guard)",
                )
            ])
        except Exception as error:
            if _conditional_failure(error):
                return
            raise

    def recover_stale_turn(
        self,
        *,
        owner_id: str,
        conversation_id: UUID,
        stale_before: datetime,
        updated_at: datetime,
    ) -> None:
        scope = current_application_scope()
        metadata = self.conversations._metadata_item_for(owner_id, conversation_id, scope)
        if metadata is None:
            raise ResourceNotFoundError("conversation not found")
        history = self._read_history(owner_id, conversation_id, scope, timeout=5)
        active = active_path(history)
        stale = [m for m in active if m.status is MessageStatus.STREAMING and m.created_at < stale_before]
        started = metadata.get("context_preparation_started_at")
        expired = bool(started and _parse_timestamp(started) < stale_before)
        if not stale and not expired:
            return
        if len(stale) + 4 > MAX_DYNAMO_TRANSACTION_ITEMS:
            raise StorageUnavailableError("stale turn recovery bound exceeded")
        conversation = _conversation_from_item(metadata)
        updated_conversation = conversation.model_copy(update={"updated_at": _utc(updated_at)})
        revision = int(metadata["revision"])
        operations = []
        for message in stale:
            failed = message.model_copy(update={"status": MessageStatus.FAILED, "error_code": "turn_interrupted"})
            operations.append(_update(
                _message_key(scope, conversation_id, message.created_at, message.id, owner_id),
                "SET #status=:status,#payload=:payload",
                names={"#status": "status", "#owner": "owner_id", "#payload": "payload"},
                values={":status": MessageStatus.FAILED.value, ":owner": owner_id,
                        ":payload": _json(_message_payload(failed))},
                condition="#owner=:owner AND #status=:streaming",
                more_values={":streaming": MessageStatus.STREAMING.value},
            ))
        update_expression = "SET #payload=:payload,#updated=:updated,#revision=:next"
        if expired:
            update_expression += " REMOVE context_preparation_id,context_preparation_started_at"
        operations.append(_update(
            _conversation_keys(scope, conversation_id, owner_id).meta,
            update_expression,
            names={"#payload": "payload", "#updated": "updated_at", "#revision": "revision", "#owner": "owner_id"},
            values={":payload": _json(_conversation_payload(updated_conversation)),
                    ":updated": _timestamp(updated_at), ":next": revision + 1,
                    ":owner": owner_id, ":revision": revision},
            condition="#owner=:owner AND revision=:revision AND attribute_not_exists(effect_guard)",
        ))
        self._append_catalog_move(operations, scope, conversation, updated_conversation, revision + 1)
        self.table.transact(operations)

    def supersede_path(self, *, owner_id: str, conversation_id: UUID, message_id: UUID, updated_at: datetime):
        self.get(owner_id=owner_id, conversation_id=conversation_id, message_id=message_id)
        scope = current_application_scope()
        history = self._read_history(owner_id, conversation_id, scope, timeout=5)
        by_id = {message.id: message for message in history}
        descendants = descendant_ids(history, message_id)
        replaced = [
            by_id[identifier] for identifier in descendants
            if identifier in by_id and effective_message(by_id[identifier], by_id).status is not MessageStatus.SUPERSEDED
        ]
        self.prepare_message_turn(
            owner_id=owner_id,
            conversation_id=conversation_id,
            expected_active_ids=[message.id for message in active_path(history)],
            supersede_from_message_id=message_id,
            messages=(),
            updated_at=updated_at,
        )
        return [message.model_copy(update={"status": MessageStatus.SUPERSEDED})
                for message in sorted(replaced, key=lambda item: (item.created_at, str(item.id)))]

    def _read_history(self, owner_id: str, conversation_id: UUID, scope: ApplicationScope,
                      timeout: float = 5, *, deadline: float | None = None):
        keys = _conversation_keys(scope, conversation_id, owner_id)
        deadline = deadline or monotonic() + timeout
        items = self.table.query(
            partition=keys.partition,
            sort_prefix="MSG#",
            consistent=True,
            deadline=deadline,
            limit=MAX_CONVERSATION_MESSAGES + 1,
        )
        if len(items) > MAX_CONVERSATION_MESSAGES:
            raise StorageUnavailableError("conversation history exceeds bound")
        messages = []
        for item in items:
            if not _authorized(item, owner_id, scope):
                continue
            try:
                messages.append(_message_from_item(item))
            except (ValueError, TypeError, KeyError) as error:
                raise StorageUnavailableError("message record invalid") from error
        return messages

    @staticmethod
    def _append_catalog_move(operations, scope, old, new, revision):
        old_key = _catalog_key(scope, old.id, old.updated_at, old.owner_id)
        item = _catalog_item(new, revision=revision)
        new_key = {"PK": item["PK"], "SK": item["SK"]}
        if old_key != new_key:
            operations.extend([_delete(old_key), _put(item, condition="attribute_not_exists(PK)")])
        else:
            operations.append(_update(
                old_key,
                "SET #revision=:revision,#updated=:updated",
                names={"#revision": "revision", "#updated": "updated_at", "#owner": "owner_id"},
                values={":revision": revision, ":updated": _timestamp(new.updated_at),
                        ":owner": new.owner_id},
                condition="#owner=:owner",
            ))


class DynamoDBMemoryJobRepository:
    """Fenced lifecycle execution jobs with one sparse, eventual publication GSI."""

    def __init__(self, table: DynamoDBRuntimeTable) -> None:
        self.table = table

    def create_job(self, job):
        from personal_ai.memory.lifecycle import MemoryJob
        from personal_ai.memory.lifecycle_repositories import job_idempotency_id

        job = scoped_record(job)
        if job.id != job_idempotency_id(job.idempotency_key, job.application_id, job.workspace_id):
            raise ValueError("job_identity_invalid")
        scope = _scope_of(job)
        key = _job_key(scope, job.id, job.owner_id)
        existing = self.table.get(key)
        if existing is not None:
            current = MemoryJob.model_validate(json.loads(existing["payload"]))
            if not _authorized(existing, job.owner_id, scope):
                raise ResourceNotFoundError("memory job not found")
            if _same_job_intent(current, job):
                return current, False
            raise ValueError("idempotency_key_reused")
        item = _job_item(job, revision=1)
        catalog = _job_catalog_item(job, scope)
        owner_catalog = _owner_job_catalog_item(job, scope)
        locator = _job_id_locator(job, scope)
        operations = [
            _put(item, condition="attribute_not_exists(PK)"),
            _put(catalog, condition="attribute_not_exists(PK)"),
            _put(owner_catalog, condition="attribute_not_exists(PK)"),
            _put(locator, condition="attribute_not_exists(PK)"),
            *_namespace_puts(self.table, job.owner_id, scope),
        ]
        try:
            self.table.transact(operations)
        except Exception as error:
            existing = self.table.get(key)
            if existing is not None:
                current = MemoryJob.model_validate(json.loads(existing["payload"]))
                if _same_job_intent(current, job):
                    return current, False
                raise ValueError("idempotency_key_reused") from error
            raise
        return job, True

    def get_job(self, *, owner_id: str, job_id: UUID):
        scope = current_application_scope()
        return self._read_job(owner_id, job_id, scope)

    def get_job_by_id(self, *, job_id: UUID, scope: ApplicationScope | None = None):
        from personal_ai.memory.lifecycle import MemoryJob

        scope = scope or current_application_scope()
        locator = self.table.get({"PK": f"JOBID#{job_id}", "SK": "LOCATOR"})
        if locator is None or not _authorized(locator, locator.get("owner_id", ""), scope):
            raise ResourceNotFoundError("memory job not found")
        item = self.table.get({"PK": locator["record_pk"], "SK": locator["record_sk"]})
        if item is None or not _authorized(item, locator["owner_id"], scope):
            raise ResourceNotFoundError("memory job not found")
        try:
            return MemoryJob.model_validate(json.loads(item["payload"]))
        except (ValueError, TypeError, KeyError) as error:
            raise StorageUnavailableError("memory job invalid") from error

    def claim_job(self, *, owner_id: str, job_id: UUID, now: datetime, lease_seconds: int):
        from uuid import uuid4

        scope = current_application_scope()
        item = self.table.get(_job_key(scope, job_id, owner_id))
        job = self._decode_job(item, owner_id, scope)
        if item.get("pending_effect") is not None:
            # Recovery must settle the P receipt before any newer generation can
            # replace the job token or act on these source conversations.
            return None
        now = _utc(now)
        if job.status in {"completed", "terminal"}:
            return None
        if job.status == "leased" and job.lease_expires_at and job.lease_expires_at > now:
            return None
        if job.next_attempt_at and job.next_attempt_at > now:
            return None
        revision = int(item["revision"])
        if job.attempt_count >= job.max_attempts:
            terminal = job.model_copy(update={
                "status": "terminal", "retry_reason": "attempts_exhausted", "updated_at": now
            })
            self._save_job(item, terminal, revision, remove_publication=True)
            return None
        claimed = job.model_copy(update={
            "status": "leased",
            "attempt_count": job.attempt_count + 1,
            "lease_expires_at": now + timedelta(seconds=lease_seconds),
            "lease_token": uuid4(),
            "lease_generation": job.lease_generation + 1,
            "publish_pending": False,
            "updated_at": now,
        })
        self._save_job(item, claimed, revision, remove_publication=True)
        return claimed

    def complete_job(self, job, *, token: UUID, now: datetime):
        return self._mutate_fenced(
            job,
            token,
            now,
            {
                "status": "completed", "lease_expires_at": None, "lease_token": None,
                "retry_reason": None, "publish_pending": False,
            },
        )

    def fail_job(self, job, *, token: UUID, now: datetime, reason: str, retryable: bool):
        now = _utc(now)
        retry = retryable and job.attempt_count < job.max_attempts
        delay = min(300, 2 ** max(0, job.attempt_count - 1))
        return self._mutate_fenced(
            job,
            token,
            now,
            {
                "status": "retry" if retry else "terminal",
                "retry_reason": reason[:100],
                "next_attempt_at": now + timedelta(seconds=delay) if retry else None,
                "lease_expires_at": None,
                "lease_token": None,
                "publish_pending": retry,
            },
        )

    def mark_published(self, *, owner_id: str, job_id: UUID, updated_at: datetime):
        scope = current_application_scope()
        item = self.table.get(_job_key(scope, job_id, owner_id))
        job = self._decode_job(item, owner_id, scope)
        if job.status not in {"pending", "retry"} or job.updated_at != _utc(updated_at):
            return job
        return self._save_job(
            item,
            job.model_copy(update={"publish_pending": False, "updated_at": _utc(updated_at)}),
            int(item["revision"]),
            remove_publication=True,
        )

    def pending_for_publish(self, *, now: datetime, limit: int = 50):
        if not 1 <= limit <= 100:
            raise ValueError("job_limit_invalid")
        now = _utc(now)
        candidates = []
        namespaces = self.table.query(
            partition="MAINT#NAMESPACES",
            sort_prefix="NS#",
            consistent=True,
            deadline=monotonic() + 10,
            limit=501,
        )
        if len(namespaces) > 500:
            raise StorageUnavailableError("memory job namespace inventory exceeds bound")
        inspected = 0
        for namespace_item in namespaces:
            scope = ApplicationScope(
                application_id=namespace_item["application_id"],
                workspace_id=(
                    namespace_item["workspace_id"]
                    if namespace_item.get("workspace_id_present") else None
                ),
            )
            namespace = namespace_item["namespace"]
            for status in ("pending", "retry"):
                partition = f"PUB#{namespace}#{status}"
                cursor = None
                eligible_for_partition = 0
                reads = 0
                while eligible_for_partition < limit and reads < 1000:
                    request = {
                        "TableName": self.table.table_name,
                        "IndexName": "job-publication-v1",
                        "KeyConditionExpression": "#pk=:pk",
                        "ExpressionAttributeNames": {"#pk": "PUBPK"},
                        "ExpressionAttributeValues": _marshal({":pk": partition}),
                        "ScanIndexForward": True,
                        "Limit": min(100, 1000 - reads),
                    }
                    if cursor:
                        request["ExclusiveStartKey"] = _marshal(cursor)
                    page = self.table.client.query(**request)
                    indexed_items = [_unmarshal(value) for value in page.get("Items", ())]
                    reads += len(indexed_items)
                    inspected += len(indexed_items)
                    if inspected > 10_000:
                        raise StorageUnavailableError("memory job publication scan bound exceeded")
                    for indexed in indexed_items:
                        canonical = self.table.get({"PK": indexed["record_pk"], "SK": indexed["record_sk"]})
                        if canonical is None:
                            raise StorageUnavailableError("memory job publication locator invalid")
                        job = self._decode_job(canonical, namespace_item["owner_id"], scope)
                        if (
                            canonical.get("status") == status
                            and job.publish_pending
                            and (job.next_attempt_at is None or job.next_attempt_at <= now)
                        ):
                            candidates.append(job)
                            eligible_for_partition += 1
                            if eligible_for_partition == limit:
                                break
                    cursor = _unmarshal(page["LastEvaluatedKey"]) if page.get("LastEvaluatedKey") else None
                    if not cursor:
                        break
                if cursor and reads >= 1000 and eligible_for_partition < limit:
                    raise StorageUnavailableError("memory job publication window exceeds bound")
        return tuple(sorted(candidates, key=lambda item: (item.created_at, str(item.id)))[:limit])

    def _read_job(self, owner_id, job_id, scope):
        item = self.table.get(_job_key(scope, job_id, owner_id))
        return self._decode_job(item, owner_id, scope)

    @staticmethod
    def _decode_job(item, owner_id, scope):
        from personal_ai.memory.lifecycle import MemoryJob

        if item is None or not _authorized(item, owner_id, scope):
            raise ResourceNotFoundError("memory job not found")
        try:
            return MemoryJob.model_validate(json.loads(item["payload"]))
        except (ValueError, TypeError, KeyError) as error:
            raise StorageUnavailableError("memory job invalid") from error

    def _save_job(self, item, updated, revision, *, remove_publication):
        job_item = _job_item(updated, revision=revision + 1)
        sets = ["#payload=:payload", "#status=:status", "#revision=:next", "#updated=:updated"]
        removes = []
        names = {"#payload": "payload", "#status": "status", "#revision": "revision",
                 "#updated": "updated_at", "#owner": "owner_id"}
        values = {":payload": job_item["payload"], ":status": updated.status,
                  ":next": revision + 1, ":updated": _timestamp(updated.updated_at),
                  ":revision": revision, ":owner": updated.owner_id}
        if updated.status == "leased":
            sets.extend(["#lease_token=:lease_token", "#lease_generation=:lease_generation",
                         "#lease_expires=:lease_expires"])
            names.update({"#lease_token": "lease_token", "#lease_generation": "lease_generation",
                          "#lease_expires": "lease_expires_at"})
            values.update({":lease_token": str(updated.lease_token),
                           ":lease_generation": updated.lease_generation,
                           ":lease_expires": _timestamp(updated.lease_expires_at)})
        else:
            removes.extend(["lease_token", "lease_generation", "lease_expires_at"])
        if job_item.get("PUBPK"):
            sets.extend(["PUBPK=:pubpk", "PUBSK=:pubsk", "record_pk=:recordpk",
                         "record_sk=:recordsk", "publish_after=:after"])
        else:
            removes.extend(["PUBPK", "PUBSK", "record_pk", "record_sk", "publish_after"])
        sets.append("job_id=:jobid")
        values[":jobid"] = str(updated.id)
        if job_item.get("PUBPK"):
            values.update({":pubpk": job_item["PUBPK"], ":pubsk": job_item["PUBSK"],
                           ":recordpk": job_item["record_pk"], ":recordsk": job_item["record_sk"],
                           ":after": job_item["publish_after"]})
        expression = "SET " + ",".join(sets)
        if removes:
            expression += " REMOVE " + ",".join(removes)
        try:
            self.table.transact([_update(
                {"PK": item["PK"], "SK": item["SK"]},
                expression,
                names=names,
                values=values,
                condition="#owner=:owner AND revision=:revision AND attribute_not_exists(pending_effect)",
            )])
        except Exception as error:
            if _conditional_failure(error):
                return False
            raise
        return updated

    def _mutate_fenced(self, job, token, now, changes):

        scope = _scope_of(job)
        item = self.table.get(_job_key(scope, job.id, job.owner_id))
        current = self._decode_job(item, job.owner_id, scope)
        now = _utc(now)
        if (
            item.get("pending_effect") is not None
            or
            current.status != "leased"
            or current.lease_token != token
            or current.lease_generation != job.lease_generation
            or current.lease_expires_at is None
            or current.lease_expires_at <= now
        ):
            return False
        updated = current.model_copy(update={**changes, "updated_at": now})
        return self._save_job(item, updated, int(item["revision"]), remove_publication=True)


class DynamoDBSummaryRepository:
    """Append-only summaries published only after bounded provenance chunks."""

    def __init__(self, table: DynamoDBRuntimeTable, conversations: DynamoDBConversationRepository | None = None):
        self.table = table
        self.conversations = conversations or DynamoDBConversationRepository(table)

    def create(self, summary: ConversationSummary) -> ConversationSummary:
        summary = scoped_record(summary)
        scope = _scope_of(summary)
        self.conversations.get(owner_id=summary.owner_id, conversation_id=summary.conversation_id)
        source_chunks = _chunks(summary.source_message_ids)
        coverage_is_implicit = not summary.coverage_message_ids
        coverage_chunks = _chunks(summary.coverage_message_ids)
        if len(source_chunks) + len(coverage_chunks) > MAX_SUMMARY_CHUNKS:
            raise StorageUnavailableError("summary provenance bound exceeded")
        keys = _conversation_keys(scope, summary.conversation_id, summary.owner_id)
        source_manifest = _chunk_manifest(source_chunks)
        coverage_manifest = _chunk_manifest(coverage_chunks)
        coverage_manifest["implicit_source"] = coverage_is_implicit
        chunks = []
        for kind, values, manifest in (
            ("source", source_chunks, source_manifest),
            ("coverage", coverage_chunks, coverage_manifest),
        ):
            for sequence, values_chunk in enumerate(values):
                item = {
                    "PK": keys.partition,
                    "SK": f"SC#{summary.id}#{kind}#{sequence:06d}",
                    "owner_id": summary.owner_id,
                    "application_id": scope.application_id,
                    "workspace_id_present": scope.workspace_id is not None,
                    "workspace_id": scope.workspace_id or "",
                    "summary_id": str(summary.id),
                    "kind": kind,
                    "sequence": sequence,
                    "payload": _json([str(identifier) for identifier in values_chunk]),
                    "chunk_sha256": manifest["hashes"][sequence],
                    "published": False,
                }
                if _item_size(item) > MAX_DYNAMO_ITEM_BYTES:
                    raise StorageUnavailableError("summary chunk too large")
                chunks.append(item)
        # Chunks are immutable deterministic staging rows. A failed publication
        # leaves only unreadable chunks; the summary header is the publish point.
        for offset in range(0, len(chunks), 25):
            batch = chunks[offset : offset + 25]
            self._put_chunks_idempotently(batch)
        data = summary.model_dump(mode="json")
        data.pop("source_message_ids")
        data.pop("coverage_message_ids")
        item = {
            "PK": keys.partition,
            "SK": f"SUM#{_timestamp(summary.created_at)}#{summary.id}",
            "kind": "summary",
            "owner_id": summary.owner_id,
            "application_id": scope.application_id,
            "workspace_id_present": scope.workspace_id is not None,
            "workspace_id": scope.workspace_id or "",
            "summary_id": str(summary.id),
            "created_at": _timestamp(summary.created_at),
            "source_manifest": _json(source_manifest),
            "coverage_manifest": _json(coverage_manifest),
            "payload": _json(data),
            "published": True,
        }
        try:
            self.table.transact([_put(item, condition="attribute_not_exists(PK)")])
        except Exception as error:
            existing = self.table.get({"PK": item["PK"], "SK": item["SK"]})
            if existing is None:
                raise
            if any(
                existing.get(field) != item.get(field)
                for field in ("payload", "source_manifest", "coverage_manifest")
            ):
                raise ConversationConflictError("summary identity payload changed") from error
        return summary

    def compatible(self, *, owner_id: str, conversation_id: UUID, active: Sequence[Message]):
        scope = current_application_scope()
        self.conversations.get(owner_id=owner_id, conversation_id=conversation_id)
        deadline = monotonic() + 5
        keys = _conversation_keys(scope, conversation_id, owner_id)
        candidates = self.table.query(
            partition=keys.partition,
            sort_prefix="SUM#",
            consistent=True,
            descending=True,
            deadline=deadline,
            limit=101,
        )
        overflow = len(candidates) > 100
        candidates = candidates[:100]
        summaries = []
        for item in candidates:
            if not item.get("published") or not _authorized(item, owner_id, scope):
                continue
            try:
                summaries.append(self._load(item, keys.partition, deadline))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
                raise StorageUnavailableError("summary provenance invalid") from error
        selected = newest_compatible(summaries, active)
        if selected is None and overflow:
            raise StorageUnavailableError("summary compatibility window exceeds bound")
        return selected

    def _load(self, item, partition, deadline):
        source_manifest = json.loads(item["source_manifest"])
        coverage_manifest = json.loads(item["coverage_manifest"])
        if source_manifest["chunks"] + coverage_manifest["chunks"] > MAX_SUMMARY_CHUNKS:
            raise StorageUnavailableError("summary chunk manifest invalid")
        source = self._load_manifest(partition, item["summary_id"], "source", source_manifest, deadline)
        coverage = (
            () if coverage_manifest.get("implicit_source")
            else self._load_manifest(partition, item["summary_id"], "coverage", coverage_manifest, deadline)
        )
        payload = json.loads(item["payload"])
        return ConversationSummary.model_validate({
            **payload,
            "source_message_ids": source,
            "coverage_message_ids": coverage,
        })

    def _load_manifest(self, partition, summary_id, kind, manifest, deadline):
        if manifest["chunks"] > MAX_SUMMARY_CHUNKS:
            raise StorageUnavailableError("summary chunk manifest invalid")
        chunks = self.table.query(
            partition=partition,
            sort_prefix=f"SC#{summary_id}#{kind}#",
            consistent=True,
            deadline=deadline,
            limit=manifest["chunks"],
        )
        values = []
        hashes = []
        for expected, item in enumerate(chunks):
            if item.get("sequence") != expected or item.get("kind") != kind:
                raise StorageUnavailableError("summary chunk sequence invalid")
            chunk = json.loads(item["payload"])
            actual_hash = hashlib.sha256(_json(chunk).encode()).hexdigest()
            if actual_hash != item.get("chunk_sha256") or actual_hash != manifest["hashes"][expected]:
                raise StorageUnavailableError("summary chunk hash invalid")
            values.extend(UUID(identifier) for identifier in chunk)
            hashes.append(actual_hash)
        if len(chunks) != manifest["chunks"] or len(values) != manifest["count"]:
            raise StorageUnavailableError("summary chunk count invalid")
        if _sequence_hash(values) != manifest["sha256"]:
            raise StorageUnavailableError("summary provenance hash invalid")
        return tuple(values)

    def _put_chunks_idempotently(self, items):
        if not items:
            return
        partition = items[0]["PK"]
        summary_id = items[0]["summary_id"]
        existing = self.table.query(
            partition=partition,
            sort_prefix=f"SC#{summary_id}#",
            consistent=True,
            deadline=monotonic() + 5,
            limit=MAX_SUMMARY_CHUNKS + 1,
        )
        if len(existing) > MAX_SUMMARY_CHUNKS:
            raise StorageUnavailableError("summary staging exceeds bound")
        existing_by_key = {entry["SK"]: entry for entry in existing}
        missing = []
        for item in items:
            current = existing_by_key.get(item["SK"])
            if current is None:
                missing.append(item)
            elif current.get("chunk_sha256") != item["chunk_sha256"]:
                raise ConversationConflictError("summary chunk identity conflict")
        for offset in range(0, len(missing), 25):
            batch = missing[offset : offset + 25]
            try:
                self.table.transact([
                    _put(item, condition="attribute_not_exists(PK)") for item in batch
                ])
            except Exception as error:
                for item in batch:
                    current = self.table.get({"PK": item["PK"], "SK": item["SK"]})
                    if current is None or current.get("chunk_sha256") != item["chunk_sha256"]:
                        raise ConversationConflictError("summary chunk identity conflict") from error


class DynamoDBMemoryEffectGuard:
    """Conversation metadata guards and direct-operation receipts in DynamoDB."""

    def __init__(self, table: DynamoDBRuntimeTable, messages: DynamoDBMessageRepository) -> None:
        self.table = table
        self.messages = messages

    def acquire(
        self, record: Any, *, timeout: float, operation_id: str | None = None,
        fingerprint_value: str | None = None,
        extra_conversation_ids: tuple[UUID, ...] = (),
        completed_assistant_id: UUID | None = None,
    ) -> EffectGuardToken:
        owner_id = record.owner_id
        scope = ApplicationScope(application_id=record.application_id, workspace_id=record.workspace_id)
        refs = _source_refs(record)
        if not refs or len(refs) > 4:
            raise ConversationConflictError("memory source set invalid")
        deadline = monotonic() + timeout
        operation_id = operation_id or str(record.id)
        fp = fingerprint_value or _record_fingerprint(record)
        if not operation_id or len(operation_id) > 512:
            raise ValueError("memory_effect_operation_id_invalid")
        guarded_conversations = sorted(
            {ref["conversation_id"] for ref in refs}
            | {str(value) for value in extra_conversation_ids},
            key=str,
        )
        first_ref = refs[0]
        first_partition = _conversation_keys(
            scope, UUID(first_ref["conversation_id"]), owner_id
        ).partition
        prior_operations = self.table.query(
            partition=first_partition,
            sort_prefix=f"OP#{operation_id}#",
            consistent=True,
            deadline=deadline,
            limit=100,
        )
        matching = [item for item in prior_operations if item.get("fingerprint") == fp]
        prior = max(matching, key=lambda item: item.get("created_at", ""), default=None)
        if prior is not None and prior.get("status") == "applied":
            return EffectGuardToken(
                owner_id=owner_id,
                operation_id=operation_id,
                attempt_id=prior["attempt_id"],
                fingerprint=fp,
                execution_deadline=_parse_timestamp(prior["execution_deadline"]),
                scope=scope,
                coordination_conversation_id=UUID(first_ref["conversation_id"]),
            )
        snapshots = {}
        for conversation_id in guarded_conversations:
            metadata = self.messages.conversations._metadata_item_for(owner_id, conversation_id, scope)
            if metadata is None:
                raise ConversationConflictError("memory source not found")
            if metadata.get("context_preparation_id") or metadata.get("effect_guard"):
                guard = metadata.get("effect_guard", {})
                if guard.get("operation_id") == operation_id and guard.get("fingerprint") == fp:
                    snapshots[str(conversation_id)] = metadata
                    continue
                raise ConversationConflictError("memory source changing")
            snapshots[str(conversation_id)] = metadata
        for ref in refs:
            active = self.messages.list_active(
                owner_id=owner_id,
                conversation_id=UUID(ref["conversation_id"]),
                timeout=max(0.1, deadline - monotonic()),
            )
            sources = [message for message in active if str(message.id) in ref["user_message_ids"]]
            assistant = next((message for message in active if str(message.id) == ref["turn_id"]), None)
            if (
                assistant is None
                or assistant.status is not MessageStatus.COMPLETED
                or assistant.role.value != "assistant"
                or assistant.parent_message_id is None
                or str(assistant.parent_message_id) not in ref["user_message_ids"]
                or [str(message.id) for message in sources] != ref["user_message_ids"]
                or fingerprint(sources) != ref["source_fingerprint"]
            ):
                raise ConversationConflictError("memory source inactive")
        if completed_assistant_id is not None:
            if len(extra_conversation_ids) != 1:
                raise ConversationConflictError("assistant_conversation_invalid")
            assistant_conversation_id = extra_conversation_ids[0]
            active = self.messages.list_active(
                owner_id=owner_id, conversation_id=assistant_conversation_id,
                timeout=max(0.1, deadline - monotonic()),
            )
            assistant = next(
                (item for item in active if item.id == completed_assistant_id), None
            )
            if (
                assistant is None
                or assistant.conversation_id != assistant_conversation_id
                or assistant.owner_id != owner_id
                or not scope_matches(assistant, scope)
                or assistant.role is not MessageRole.ASSISTANT
                or assistant.status is not MessageStatus.COMPLETED
            ):
                raise ConversationConflictError("assistant_incomplete")
        existing_attempts = {
            metadata.get("effect_guard", {}).get("attempt_id")
            for metadata in snapshots.values()
            if metadata.get("effect_guard", {}).get("operation_id") == operation_id
            and metadata.get("effect_guard", {}).get("fingerprint") == fp
        }
        if prior is not None and prior.get("status") == "pending":
            attempt_id = prior["attempt_id"]
        elif len(existing_attempts) == 1:
            attempt_id = existing_attempts.pop()
        elif existing_attempts:
            raise ConversationConflictError("memory source guard attempts disagree")
        else:
            attempt_id = str(uuid4())
        operation_key = {"PK": first_partition, "SK": f"OP#{operation_id}#{attempt_id}"}
        fixed_deadline = (
            _parse_timestamp(prior["execution_deadline"])
            if prior is not None and prior.get("status") == "pending"
            else datetime.now(UTC) + timedelta(seconds=max(1, timeout))
        )
        operation_item = {
            **operation_key,
            "kind": "memory-effect",
            "owner_id": owner_id,
            "application_id": scope.application_id,
            "workspace_id_present": scope.workspace_id is not None,
            "workspace_id": scope.workspace_id or "",
            "operation_id": operation_id,
            "attempt_id": attempt_id,
            "fingerprint": fp,
            "status": "pending",
            "execution_deadline": _timestamp(fixed_deadline),
            "refs": _json(refs),
            "guard_conversations": _json(guarded_conversations),
            "coordination_conversation_id": first_ref["conversation_id"],
            "created_at": _timestamp(datetime.now(UTC)),
        }
        if _item_size(operation_item) > MAX_DYNAMO_ITEM_BYTES:
            raise StorageUnavailableError("memory effect guard too large")
        operations = []
        for conversation_key, metadata in snapshots.items():
            conversation_id = UUID(conversation_key)
            key = _conversation_keys(scope, conversation_id, owner_id).meta
            revision = int(metadata["revision"])
            guard = {
                "operation_id": operation_id,
                "attempt_id": attempt_id,
                "fingerprint": fp,
                "execution_deadline": _timestamp(fixed_deadline),
                "source_conversation_id": conversation_key,
            }
            operations.append(_update(
                key,
                "SET effect_guard=:guard",
                names={"#owner": "owner_id", "#revision": "revision"},
                values={":guard": guard, ":owner": owner_id, ":revision": revision,
                        ":attempt": attempt_id, ":operation": operation_id},
                condition="#owner=:owner AND #revision=:revision AND attribute_not_exists(context_preparation_id) "
                          "AND (attribute_not_exists(effect_guard) OR (effect_guard.operation_id=:operation "
                          "AND effect_guard.attempt_id=:attempt))",
            ))
        old_operation = self.table.get(operation_key)
        if old_operation is None:
            if not (prior and prior.get("status") == "pending"):
                operation_item["execution_deadline"] = _timestamp(fixed_deadline)
                operations.append(_put(operation_item, condition="attribute_not_exists(PK)"))
                operations.append(_put({
                    "PK": f"{_namespace(scope, owner_id)}#OPS",
                    "SK": f"DIRECT#{first_ref['conversation_id']}#{operation_id}#{attempt_id}",
                    "kind": "pending-memory-effect",
                    "effect_kind": "direct",
                    "owner_id": owner_id,
                    "application_id": scope.application_id,
                    "workspace_id_present": scope.workspace_id is not None,
                    "workspace_id": scope.workspace_id or "",
                    "operation_pk": operation_key["PK"],
                    "operation_sk": operation_key["SK"],
                    "conversation_id": first_ref["conversation_id"],
                    "created_at": _timestamp(datetime.now(UTC)),
                }, condition="attribute_not_exists(PK)"))
        elif old_operation.get("fingerprint") != fp:
            raise ConversationConflictError("memory effect identity conflict")
        else:
            fixed_deadline = _parse_timestamp(old_operation["execution_deadline"])
        if operations:
            self.table.transact(operations)
        self._operation_conversations = getattr(self, "_operation_conversations", {})
        self._operation_conversations[(operation_id, attempt_id)] = first_ref["conversation_id"]
        return EffectGuardToken(
            owner_id=owner_id,
            operation_id=operation_id,
            attempt_id=attempt_id,
            fingerprint=fp,
            execution_deadline=fixed_deadline,
            scope=scope,
            coordination_conversation_id=UUID(first_ref["conversation_id"]),
        )

    def acquire_lifecycle_event(
        self, record: Any, *, operation_id: str, fingerprint: str,
        completed_assistant_id: UUID | None,
        completed_assistant_conversation_id: UUID | None, timeout: float,
    ) -> EffectGuardToken:
        extra = () if completed_assistant_conversation_id is None else (
            completed_assistant_conversation_id,
        )
        return self.acquire(
            record, timeout=timeout, operation_id=operation_id,
            fingerprint_value=fingerprint, extra_conversation_ids=extra,
            completed_assistant_id=completed_assistant_id,
        )

    def acquire_job(
        self,
        job: Any,
        lease_token: UUID,
        record: Any,
        *,
        operation_id: str,
        timeout: float,
    ) -> EffectGuardToken:
        """Fence a P effect with the live D job generation and its chat sources."""
        from personal_ai.memory.lifecycle import MemoryJob

        if not isinstance(job, MemoryJob) or not operation_id or len(operation_id) > 512:
            raise ValueError("memory_job_effect_invalid")
        owner_id = job.owner_id
        scope = _scope_of(job)
        if (
            getattr(record, "owner_id", None) != owner_id
            or (getattr(record, "application_id", None), getattr(record, "workspace_id", None))
            != (scope.application_id, scope.workspace_id)
        ):
            raise ConversationConflictError("memory job effect scope changed")
        refs = _source_refs(record)
        if len(refs) > 4:
            raise ConversationConflictError("memory source set invalid")
        deadline = monotonic() + timeout
        job_key = _job_key(scope, job.id, owner_id)
        item = self.table.get(job_key)
        current = DynamoDBMemoryJobRepository._decode_job(item, owner_id, scope)
        now = datetime.now(UTC)
        if (
            current.status != "leased"
            or current.lease_token != lease_token
            or current.lease_generation != job.lease_generation
            or current.lease_expires_at is None
            or current.lease_expires_at <= now
        ):
            raise ConversationConflictError("memory job lease changed")
        fingerprint_value = _record_fingerprint(record)
        generation_attempt = f"g{current.lease_generation}:{lease_token}"
        acknowledged = item.get("last_effect_ack")
        if (
            acknowledged is not None
            and acknowledged.get("operation_id") == operation_id
            and acknowledged.get("attempt_id") == generation_attempt
            and acknowledged.get("fingerprint") == fingerprint_value
            and acknowledged.get("lease_generation") == current.lease_generation
        ):
            if acknowledged.get("outcome") == "aborted":
                raise ConversationConflictError("memory job effect attempt was aborted")
            if acknowledged.get("outcome") == "applied":
                return EffectGuardToken(
                    owner_id=owner_id,
                    operation_id=operation_id,
                    attempt_id=generation_attempt,
                    fingerprint=fingerprint_value,
                    execution_deadline=_parse_timestamp(acknowledged["execution_deadline"]),
                    scope=scope,
                    coordination_conversation_id=(
                        UUID(refs[0]["conversation_id"]) if refs else None
                    ),
                    coordination_job_id=job.id,
                    lease_generation=current.lease_generation,
                )
        prior = item.get("pending_effect")
        if prior is not None:
            if (
                prior.get("operation_id") == operation_id
                and prior.get("attempt_id") == generation_attempt
                and prior.get("fingerprint") == fingerprint_value
            ):
                return EffectGuardToken(
                    owner_id=owner_id,
                    operation_id=operation_id,
                    attempt_id=generation_attempt,
                    fingerprint=fingerprint_value,
                    execution_deadline=_parse_timestamp(prior["execution_deadline"]),
                    scope=scope,
                    coordination_conversation_id=(
                        UUID(refs[0]["conversation_id"]) if refs else None
                    ),
                    coordination_job_id=job.id,
                    lease_generation=current.lease_generation,
                )
            raise ConversationConflictError("memory job effect already pending")

        snapshots = {}
        for conversation_id in sorted({ref["conversation_id"] for ref in refs}):
            metadata = self.messages.conversations._metadata_item_for(
                owner_id, UUID(conversation_id), scope
            )
            if metadata is None:
                raise ConversationConflictError("memory source not found")
            if metadata.get("context_preparation_id") or metadata.get("effect_guard"):
                raise ConversationConflictError("memory source changing")
            snapshots[conversation_id] = metadata
        for ref in refs:
            active = self.messages.list_active(
                owner_id=owner_id,
                conversation_id=UUID(ref["conversation_id"]),
                timeout=max(0.1, deadline - monotonic()),
            )
            by_id = {str(message.id): message for message in active}
            sources = [by_id.get(identifier) for identifier in ref["user_message_ids"]]
            assistant = by_id.get(ref["turn_id"])
            if (
                any(source is None or source.role.value != "user" for source in sources)
                or assistant is None
                or assistant.status is not MessageStatus.COMPLETED
                or assistant.role.value != "assistant"
                or assistant.parent_message_id is None
                or str(assistant.parent_message_id) not in ref["user_message_ids"]
                or fingerprint(sources) != ref["source_fingerprint"]
            ):
                raise ConversationConflictError("memory source inactive")

        execution_deadline = min(
            current.lease_expires_at,
            now + timedelta(seconds=max(1, timeout)),
        )
        if execution_deadline <= now:
            raise ConversationConflictError("memory job lease expired")
        pending = {
            "operation_id": operation_id,
            "attempt_id": generation_attempt,
            "fingerprint": fingerprint_value,
            "lease_generation": current.lease_generation,
            "lease_token": str(lease_token),
            "execution_deadline": _timestamp(execution_deadline),
            "refs": _json(refs),
        }
        if _item_size({**item, "pending_effect": pending}) > MAX_DYNAMO_ITEM_BYTES:
            raise StorageUnavailableError("memory job effect guard too large")
        operations = []
        for conversation_id, metadata in snapshots.items():
            key = _conversation_keys(scope, UUID(conversation_id), owner_id).meta
            operations.append(_update(
                key,
                "SET effect_guard=:guard",
                names={"#owner": "owner_id", "#revision": "revision"},
                values={
                    ":guard": {
                        "operation_id": operation_id,
                        "attempt_id": generation_attempt,
                        "fingerprint": fingerprint_value,
                        "execution_deadline": _timestamp(execution_deadline),
                        "job_id": str(job.id),
                        "lease_generation": current.lease_generation,
                    },
                    ":owner": owner_id,
                    ":revision": int(metadata["revision"]),
                },
                condition="#owner=:owner AND #revision=:revision "
                          "AND attribute_not_exists(context_preparation_id) "
                          "AND attribute_not_exists(effect_guard)",
            ))
        operations.append(_update(
            job_key,
            "SET pending_effect=:pending,#revision=:next",
            names={"#owner": "owner_id", "#revision": "revision", "#status": "status",
                   "#token": "lease_token", "#generation": "lease_generation",
                   "#expires": "lease_expires_at"},
            values={
                ":pending": pending,
                ":next": int(item["revision"]) + 1,
                ":revision": int(item["revision"]),
                ":owner": owner_id,
                ":leased": "leased",
                ":token": str(lease_token),
                ":generation": current.lease_generation,
                ":now": _timestamp(now),
            },
            condition="#owner=:owner AND #status=:leased AND revision=:revision "
                      "AND #token=:token AND #generation=:generation AND #expires>:now "
                      "AND attribute_not_exists(pending_effect)",
        ))
        operations.append(_put({
            "PK": f"{_namespace(scope, owner_id)}#OPS",
            "SK": f"JOB#{job.id}",
            "kind": "pending-memory-effect",
            "effect_kind": "job",
            "owner_id": owner_id,
            "application_id": scope.application_id,
            "workspace_id_present": scope.workspace_id is not None,
            "workspace_id": scope.workspace_id or "",
            "job_id": str(job.id),
            "created_at": _timestamp(datetime.now(UTC)),
        }, condition="attribute_not_exists(PK)"))
        self.table.transact(operations)
        return EffectGuardToken(
            owner_id=owner_id,
            operation_id=operation_id,
            attempt_id=generation_attempt,
            fingerprint=fingerprint_value,
            execution_deadline=execution_deadline,
            scope=scope,
            coordination_conversation_id=UUID(refs[0]["conversation_id"]) if refs else None,
            coordination_job_id=job.id,
            lease_generation=current.lease_generation,
        )

    def acknowledge(self, token: EffectGuardToken, *, outcome: str, result_refs: dict[str, Any]) -> None:
        if outcome not in {"applied", "aborted"}:
            raise ValueError("memory_effect_outcome_invalid")
        if token.coordination_job_id is not None:
            self._acknowledge_job(token, outcome=outcome, result_refs=result_refs)
            return
        # The operation stores the exact source conversation references; load it
        # strongly before touching guards, then condition every guarded write.
        conversation_id = token.coordination_conversation_id
        if conversation_id is None:
            raise ConversationConflictError("memory effect coordinator missing")
        operation_key = {
            "PK": _conversation_keys(token.scope, conversation_id, token.owner_id).partition,
            "SK": f"OP#{token.operation_id}#{token.attempt_id}",
        }
        operation = self.table.get(operation_key)
        if operation is None or operation.get("fingerprint") != token.fingerprint:
            raise ConversationConflictError("memory effect operation unavailable")
        if operation.get("status") in {"applied", "aborted"}:
            if operation["status"] != outcome:
                raise ConversationConflictError("memory effect outcome conflict")
            return
        refs = json.loads(operation["refs"])
        conversations = json.loads(operation.get(
            "guard_conversations", _json(sorted({ref["conversation_id"] for ref in refs}))
        ))
        actions = []
        for conversation_key in conversations:
            key = _conversation_keys(token.scope, UUID(conversation_key), token.owner_id).meta
            metadata = self.table.get(key)
            if metadata is None:
                raise ConversationConflictError("memory source conversation unavailable")
            actions.append(_update(
                key,
                "REMOVE effect_guard",
                names={"#owner": "owner_id"},
                values={":owner": operation["owner_id"], ":operation": token.operation_id,
                        ":attempt": token.attempt_id},
                condition="#owner=:owner AND effect_guard.operation_id=:operation "
                          "AND effect_guard.attempt_id=:attempt",
            ))
        actions.append(_update(
            operation_key,
            "SET #status=:status,#result=:result,#ack=:ack",
            names={"#status": "status", "#result": "result_refs", "#ack": "acknowledged_at"},
            values={":status": outcome, ":result": _json(result_refs), ":ack": _timestamp(datetime.now(UTC)),
                    ":pending": "pending", ":fingerprint": token.fingerprint},
            condition="#status=:pending AND fingerprint=:fingerprint",
        ))
        actions.append(_delete({
            "PK": f"{_namespace(token.scope, token.owner_id)}#OPS",
            "SK": f"DIRECT#{operation['coordination_conversation_id']}#"
                 f"{token.operation_id}#{token.attempt_id}",
        }))
        self.table.transact(actions)

    def _acknowledge_job(self, token, *, outcome, result_refs):
        job_id = token.coordination_job_id
        if job_id is None:
            raise ConversationConflictError("memory job coordinator missing")
        key = _job_key(token.scope, job_id, token.owner_id)
        item = self.table.get(key)
        pending = None if item is None else item.get("pending_effect")
        acknowledged = None if item is None else item.get("last_effect_ack")
        if pending is None and acknowledged is not None and all(
                acknowledged.get(field) == value
                for field, value in (
                    ("operation_id", token.operation_id),
                    ("attempt_id", token.attempt_id),
                    ("fingerprint", token.fingerprint),
                    ("outcome", outcome),
                    ("lease_generation", token.lease_generation),
                )
            ):
            return
        if pending is None or any(
            pending.get(field) != value
            for field, value in (
                ("operation_id", token.operation_id),
                ("attempt_id", token.attempt_id),
                ("fingerprint", token.fingerprint),
                ("lease_generation", token.lease_generation),
            )
        ):
            raise ConversationConflictError("memory job effect unavailable")
        refs = json.loads(pending.get("refs", "[]"))
        actions = []
        for conversation_id in sorted({ref["conversation_id"] for ref in refs}):
            meta_key = _conversation_keys(
                token.scope, UUID(conversation_id), token.owner_id
            ).meta
            actions.append(_update(
                meta_key,
                "REMOVE effect_guard",
                names={"#owner": "owner_id"},
                values={":owner": token.owner_id, ":operation": token.operation_id,
                        ":attempt": token.attempt_id, ":job": str(job_id)},
                condition="#owner=:owner AND effect_guard.operation_id=:operation "
                          "AND effect_guard.attempt_id=:attempt AND effect_guard.job_id=:job",
            ))
        actions.append(_update(
            key,
            "SET #revision=:next,#ack=:ack REMOVE pending_effect",
            names={"#owner": "owner_id", "#revision": "revision", "#ack": "last_effect_ack"},
            values={":owner": token.owner_id, ":revision": int(item["revision"]),
                    ":next": int(item["revision"]) + 1,
                    ":operation": token.operation_id, ":attempt": token.attempt_id,
                    ":fingerprint": token.fingerprint,
                    ":generation": token.lease_generation,
                    ":ack": {
                        "operation_id": token.operation_id,
                        "attempt_id": token.attempt_id,
                        "fingerprint": token.fingerprint,
                        "lease_generation": token.lease_generation,
                        "outcome": outcome,
                        "execution_deadline": pending["execution_deadline"],
                        "result_refs": result_refs,
                        "acknowledged_at": _timestamp(datetime.now(UTC)),
                    }},
            condition="#owner=:owner AND revision=:revision "
                      "AND pending_effect.operation_id=:operation "
                      "AND pending_effect.attempt_id=:attempt "
                      "AND pending_effect.fingerprint=:fingerprint "
                      "AND pending_effect.lease_generation=:generation",
        ))
        actions.append(_delete({
            "PK": f"{_namespace(token.scope, token.owner_id)}#OPS",
            "SK": f"JOB#{job_id}",
        }))
        try:
            self.table.transact(actions)
        except Exception as error:
            if not _conditional_failure(error):
                raise
            latest = self.table.get(key)
            acknowledged = None if latest is None else latest.get("last_effect_ack")
            if acknowledged is not None and all(
                acknowledged.get(field) == value
                for field, value in (
                    ("operation_id", token.operation_id),
                    ("attempt_id", token.attempt_id),
                    ("fingerprint", token.fingerprint),
                    ("outcome", outcome),
                    ("lease_generation", token.lease_generation),
                )
            ):
                return
            raise

    def pending_operations(
        self, *, owner_id: str, conversation_id: UUID, scope: ApplicationScope, limit: int = 50
    ):
        if not 1 <= limit <= 100:
            raise ValueError("operation_limit_invalid")
        items = self.table.query(
            partition=f"{_namespace(scope, owner_id)}#OPS",
            sort_prefix=f"DIRECT#{conversation_id}#",
            consistent=True,
            deadline=monotonic() + 5,
            limit=limit,
        )
        operations = []
        for pointer in items:
            operation = self.table.get({"PK": pointer["operation_pk"], "SK": pointer["operation_sk"]})
            if (
                operation is not None and operation.get("kind") == "memory-effect"
                and operation.get("status") == "pending"
                and _authorized(operation, owner_id, scope)
            ):
                operation["coordination_conversation_id"] = str(conversation_id)
                operations.append(operation)
        return tuple(operations)

    def recover_pending(
        self, *, owner_id: str, conversation_id: UUID, scope: ApplicationScope,
        receipts, limit: int = 50,
    ) -> int:
        """Resolve every pending D guard by serializing an applied/aborted P receipt."""
        operations = self.pending_operations(
            owner_id=owner_id, conversation_id=conversation_id, scope=scope, limit=limit
        )
        for operation in operations:
            args = {
                "owner_id": owner_id,
                "scope": scope,
                "operation_id": operation["operation_id"],
                "attempt_id": operation["attempt_id"],
            }
            receipt = receipts.get(**args)
            if receipt is None:
                receipt = receipts.abort_if_unresolved(
                    **args,
                    fingerprint=operation["fingerprint"],
                    execution_deadline=_parse_timestamp(operation["execution_deadline"]),
                )
            token = EffectGuardToken(
                owner_id=owner_id,
                operation_id=operation["operation_id"],
                attempt_id=operation["attempt_id"],
                fingerprint=operation["fingerprint"],
                execution_deadline=_parse_timestamp(operation["execution_deadline"]),
                scope=scope,
                coordination_conversation_id=conversation_id,
            )
            self.acknowledge(token, outcome=receipt.outcome, result_refs=receipt.result_refs)
        return len(operations)

    def recover_pending_effects(self, *, owner_id: str, limit: int, receipts) -> int:
        """Reconcile a bounded owner namespace inventory through pending-only pointers."""
        if not 1 <= limit <= 100:
            raise ValueError("operation_limit_invalid")
        namespaces = self.table.query(
            partition="MAINT#NAMESPACES", sort_prefix="NS#", consistent=True,
            deadline=monotonic() + 10, limit=501,
        )
        if len(namespaces) > 500:
            raise StorageUnavailableError("memory effect namespace inventory exceeds bound")
        processed = 0
        for entry in namespaces:
            if entry.get("owner_id") != owner_id:
                continue
            scope = ApplicationScope(
                application_id=entry["application_id"],
                workspace_id=entry["workspace_id"] if entry.get("workspace_id_present") else None,
            )
            pointers = []
            for prefix in ("DIRECT#", "JOB#"):
                pointers.extend(self.table.query(
                    partition=f"{entry['namespace']}#OPS", sort_prefix=prefix,
                    consistent=True, deadline=monotonic() + 10, limit=limit,
                ))
            for pointer in pointers:
                if pointer.get("kind") != "pending-memory-effect" or not _authorized(pointer, owner_id, scope):
                    continue
                if pointer.get("effect_kind") == "job":
                    processed += self.recover_pending_job(
                        owner_id=owner_id, job_id=UUID(pointer["job_id"]),
                        scope=scope, receipts=receipts,
                    )
                elif pointer.get("effect_kind") == "direct":
                    operation = self.table.get({
                        "PK": pointer["operation_pk"], "SK": pointer["operation_sk"]
                    })
                    if operation is None or operation.get("status") != "pending":
                        self.table.transact([_delete({"PK": pointer["PK"], "SK": pointer["SK"]})])
                        continue
                    args = {
                        "owner_id": owner_id, "scope": scope,
                        "operation_id": operation["operation_id"],
                        "attempt_id": operation["attempt_id"],
                    }
                    receipt = receipts.get(**args)
                    if receipt is None:
                        receipt = receipts.abort_if_unresolved(
                            **args, fingerprint=operation["fingerprint"],
                            execution_deadline=_parse_timestamp(operation["execution_deadline"]),
                        )
                    token = EffectGuardToken(
                        owner_id=owner_id, operation_id=operation["operation_id"],
                        attempt_id=operation["attempt_id"], fingerprint=operation["fingerprint"],
                        execution_deadline=_parse_timestamp(operation["execution_deadline"]),
                        scope=scope,
                        coordination_conversation_id=UUID(pointer["conversation_id"]),
                    )
                    self.acknowledge(token, outcome=receipt.outcome, result_refs=receipt.result_refs)
                    processed += 1
                if processed >= limit:
                    return processed
        return processed

    def recover_pending_job(
        self, *, owner_id: str, job_id: UUID, scope: ApplicationScope, receipts
    ) -> int:
        """Recover one D job's pending P operation before allowing a new lease."""
        key = _job_key(scope, job_id, owner_id)
        item = self.table.get(key)
        if item is None or not _authorized(item, owner_id, scope):
            raise ResourceNotFoundError("memory job not found")
        pending = item.get("pending_effect")
        if pending is None:
            return 0
        args = {
            "owner_id": owner_id,
            "scope": scope,
            "operation_id": pending["operation_id"],
            "attempt_id": pending["attempt_id"],
        }
        receipt = receipts.get(**args)
        if receipt is None:
            receipt = receipts.abort_if_unresolved(
                **args,
                fingerprint=pending["fingerprint"],
                execution_deadline=_parse_timestamp(pending["execution_deadline"]),
            )
        token = EffectGuardToken(
            owner_id=owner_id,
            operation_id=pending["operation_id"],
            attempt_id=pending["attempt_id"],
            fingerprint=pending["fingerprint"],
            execution_deadline=_parse_timestamp(pending["execution_deadline"]),
            scope=scope,
            coordination_conversation_id=None,
            coordination_job_id=job_id,
            lease_generation=int(pending["lease_generation"]),
        )
        self.acknowledge(token, outcome=receipt.outcome, result_refs=receipt.result_refs)
        return 1


@dataclass(frozen=True)
class ConversationKeys:
    partition: str
    meta: dict[str, str]


def _b64(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _namespace(scope: ApplicationScope, owner_id: str) -> str:
    return "N2#" + _b64([owner_id, scope.application_id, scope.workspace_id])


def _conversation_keys(
    scope: ApplicationScope, conversation_id: UUID, owner_id: str | None = None
) -> ConversationKeys:
    owner_id = owner_id or _owner_from_scope_context()
    partition = f"{_namespace(scope, owner_id)}#CONV#{conversation_id}"
    return ConversationKeys(partition, {"PK": partition, "SK": "META"})


def _owner_from_scope_context() -> str:
    """Owner is embedded in RequestScope; low-level key helpers can also be passed via item."""
    from personal_ai.auth.scope import current_request_scope

    request_scope = current_request_scope()
    return request_scope.owner_id if request_scope is not None else "local"


def _conversation_keys_for(owner_id: str, scope: ApplicationScope, conversation_id: UUID):
    partition = f"{_namespace(scope, owner_id)}#CONV#{conversation_id}"
    return ConversationKeys(partition, {"PK": partition, "SK": "META"})


def _scope_of(record) -> ApplicationScope:
    return ApplicationScope(
        application_id=getattr(record, "application_id", "personal_ai"),
        workspace_id=getattr(record, "workspace_id", None),
    )


def _authorized(item: dict[str, Any], owner_id: str, scope: ApplicationScope) -> bool:
    application_id = item.get("application_id", "personal_ai")
    workspace_id = item.get("workspace_id") if item.get("workspace_id_present", "workspace_id" in item) else None
    if "workspace_id_present" in item and not item["workspace_id_present"]:
        workspace_id = None
    return (
        item.get("owner_id") == owner_id
        and application_id == scope.application_id
        and workspace_id == scope.workspace_id
    )


def _conversation_payload(conversation: Conversation) -> dict[str, Any]:
    return conversation.model_dump(mode="json", exclude={"context_preparation_id", "context_preparation_started_at"})


def _metadata_item(conversation: Conversation, payload: dict[str, Any], *, revision: int) -> dict[str, Any]:
    scope = _scope_of(conversation)
    item = {
        **_conversation_keys_for(conversation.owner_id, scope, conversation.id).meta,
        "kind": "conversation",
        "owner_id": conversation.owner_id,
        "application_id": scope.application_id,
        "workspace_id_present": scope.workspace_id is not None,
        "workspace_id": scope.workspace_id or "",
        "payload": _json(payload),
        "revision": revision,
        "created_at": _timestamp(conversation.created_at),
        "updated_at": _timestamp(conversation.updated_at),
    }
    if conversation.context_preparation_id is not None:
        item["context_preparation_id"] = str(conversation.context_preparation_id)
    if conversation.context_preparation_started_at is not None:
        item["context_preparation_started_at"] = _timestamp(conversation.context_preparation_started_at)
    if _item_size(item) > MAX_DYNAMO_ITEM_BYTES:
        raise StorageUnavailableError("conversation item too large")
    return item


def _conversation_from_item(item: dict[str, Any]) -> Conversation:
    payload = json.loads(item["payload"])
    if item.get("context_preparation_id"):
        payload["context_preparation_id"] = UUID(item["context_preparation_id"])
    if item.get("context_preparation_started_at"):
        payload["context_preparation_started_at"] = _parse_timestamp(item["context_preparation_started_at"])
    payload["persistence_revision"] = int(item["revision"])
    return Conversation.model_validate(payload)


def _catalog_key(
    scope: ApplicationScope, conversation_id: UUID, updated_at: datetime, owner_id: str | None = None
):
    owner = owner_id or _owner_from_scope_context()
    return {
        "PK": f"{_namespace(scope, owner)}#CATALOG",
        "SK": f"CONV#{_timestamp(updated_at)}#{conversation_id}",
    }


def _catalog_item(conversation: Conversation, *, revision: int) -> dict[str, Any]:
    scope = _scope_of(conversation)
    return {
        **_catalog_key_for(conversation.owner_id, scope, conversation.id, conversation.updated_at),
        "kind": "conversation-directory",
        "owner_id": conversation.owner_id,
        "application_id": scope.application_id,
        "workspace_id_present": scope.workspace_id is not None,
        "workspace_id": scope.workspace_id or "",
        "conversation_id": str(conversation.id),
        "updated_at": _timestamp(conversation.updated_at),
        "revision": revision,
    }


def _catalog_key_for(owner_id, scope, conversation_id, updated_at):
    return {
        "PK": f"{_namespace(scope, owner_id)}#CATALOG",
        "SK": f"CONV#{_timestamp(updated_at)}#{conversation_id}",
    }


def _namespace_puts(table: DynamoDBRuntimeTable, owner_id: str, scope: ApplicationScope):
    namespace = _namespace(scope, owner_id)
    owner_pk = f"OWNER#{_b64(owner_id)}"
    scope_key = _b64([scope.application_id, scope.workspace_id])
    entries = [
        {
            "PK": owner_pk,
            "SK": f"NS#{scope_key}",
            "kind": "owner-namespace",
            "owner_id": owner_id,
            "application_id": scope.application_id,
            "workspace_id_present": scope.workspace_id is not None,
            "workspace_id": scope.workspace_id or "",
        },
        {
            "PK": "MAINT#NAMESPACES",
            "SK": f"NS#{_b64([owner_id, scope.application_id, scope.workspace_id])}",
            "kind": "maintenance-namespace",
            "owner_id": owner_id,
            "application_id": scope.application_id,
            "workspace_id_present": scope.workspace_id is not None,
            "workspace_id": scope.workspace_id or "",
            "namespace": namespace,
        },
    ]
    operations = []
    for item in entries:
        if table.get({"PK": item["PK"], "SK": item["SK"]}) is None:
            operations.append(_put(item, condition="attribute_not_exists(PK)"))
    return operations


def _message_key(
    scope: ApplicationScope,
    conversation_id: UUID,
    created_at: datetime,
    message_id: UUID,
    owner_id: str | None = None,
):
    owner = owner_id or _owner_from_scope_context()
    partition = f"{_namespace(scope, owner)}#CONV#{conversation_id}"
    return {"PK": partition, "SK": f"MSG#{_timestamp(created_at)}#{message_id}"}


def _message_item(message: Message, scope: ApplicationScope):
    return {
        **_message_key_for(message.owner_id, scope, message.conversation_id, message.created_at, message.id),
        "kind": "message",
        "owner_id": message.owner_id,
        "application_id": scope.application_id,
        "workspace_id_present": scope.workspace_id is not None,
        "workspace_id": scope.workspace_id or "",
        "conversation_id": str(message.conversation_id),
        "message_id": str(message.id),
        "created_at": _timestamp(message.created_at),
        "status": message.status.value,
        "payload": _json(_message_payload(message)),
    }


def _message_key_for(owner_id, scope, conversation_id, created_at, message_id):
    partition = f"{_namespace(scope, owner_id)}#CONV#{conversation_id}"
    return {"PK": partition, "SK": f"MSG#{_timestamp(created_at)}#{message_id}"}


def _message_locator(message: Message, scope: ApplicationScope):
    canonical = _message_key_for(message.owner_id, scope, message.conversation_id, message.created_at, message.id)
    return {
        "PK": canonical["PK"],
        "SK": f"MID#{message.id}",
        "kind": "message-locator",
        "owner_id": message.owner_id,
        "application_id": scope.application_id,
        "workspace_id_present": scope.workspace_id is not None,
        "workspace_id": scope.workspace_id or "",
        "conversation_id": str(message.conversation_id),
        "message_id": str(message.id),
        "message_pk": canonical["PK"],
        "message_sk": canonical["SK"],
    }


def _message_payload(message: Message):
    return message.model_dump(mode="json")


def _message_from_item(item):
    return Message.model_validate(json.loads(item["payload"]))


def _job_key(scope: ApplicationScope, job_id: UUID, owner_id: str | None = None):
    if owner_id is None:
        owner_id = _owner_from_scope_context()
    partition = f"{_namespace(scope, owner_id)}#JOB#{job_id}"
    return {"PK": partition, "SK": "META"}


def _job_id_locator(job, scope):
    key = _job_key(scope, job.id, job.owner_id)
    return {
        "PK": f"JOBID#{job.id}",
        "SK": "LOCATOR",
        "kind": "service-job-locator",
        "owner_id": job.owner_id,
        "application_id": scope.application_id,
        "workspace_id_present": scope.workspace_id is not None,
        "workspace_id": scope.workspace_id or "",
        "record_pk": key["PK"],
        "record_sk": key["SK"],
    }


def _job_id_locator(job, scope):
    key = _job_key(scope, job.id, job.owner_id)
    return {
        "PK": f"JOBID#{job.id}",
        "SK": "LOCATOR",
        "kind": "service-job-locator",
        "owner_id": job.owner_id,
        "application_id": scope.application_id,
        "workspace_id_present": scope.workspace_id is not None,
        "workspace_id": scope.workspace_id or "",
        "record_pk": key["PK"],
        "record_sk": key["SK"],
    }


def _job_item(job, *, revision: int):
    scope = _scope_of(job)
    key = _job_key(scope, job.id, job.owner_id)
    item = {
        **key,
        "kind": "memory-lifecycle-job",
        "owner_id": job.owner_id,
        "application_id": scope.application_id,
        "workspace_id_present": scope.workspace_id is not None,
        "workspace_id": scope.workspace_id or "",
        "job_id": str(job.id),
        "status": job.status,
        "revision": revision,
        "created_at": _timestamp(job.created_at),
        "updated_at": _timestamp(job.updated_at),
        "payload": job.model_dump_json(),
    }
    if job.status == "leased":
        item.update({
            "lease_token": str(job.lease_token),
            "lease_generation": job.lease_generation,
            "lease_expires_at": _timestamp(job.lease_expires_at),
        })
    if job.status in {"pending", "retry"} and job.publish_pending:
        namespace = _namespace(scope, job.owner_id)
        item.update({
            "PUBPK": f"PUB#{namespace}#{job.status}",
            "PUBSK": f"{_timestamp(job.created_at)}#{job.id}",
            "record_pk": key["PK"],
            "record_sk": key["SK"],
            "publish_after": _timestamp(job.next_attempt_at or job.created_at),
        })
    if _item_size(item) > MAX_DYNAMO_ITEM_BYTES:
        raise StorageUnavailableError("memory job item too large")
    return item


def _job_catalog_item(job, scope):
    return {
        "PK": f"{_namespace(scope, job.owner_id)}#CATALOG",
        "SK": f"JOB#{job.id}",
        "kind": "job-directory",
        "owner_id": job.owner_id,
        "application_id": scope.application_id,
        "workspace_id_present": scope.workspace_id is not None,
        "workspace_id": scope.workspace_id or "",
        "job_id": str(job.id),
        "record_pk": _job_key(scope, job.id, job.owner_id)["PK"],
        "record_sk": "META",
    }


def _owner_job_catalog_item(job, scope):
    return {
        "PK": f"OWNER#{_b64(job.owner_id)}",
        "SK": f"JOB#{_b64([scope.application_id, scope.workspace_id])}#{job.id}",
        "kind": "owner-job-directory",
        "owner_id": job.owner_id,
        "application_id": scope.application_id,
        "workspace_id_present": scope.workspace_id is not None,
        "workspace_id": scope.workspace_id or "",
        "job_id": str(job.id),
    }


def _same_job_intent(first, second):
    immutable = {
        "status", "attempt_count", "lease_expires_at", "lease_token", "lease_generation",
        "publish_pending", "retry_reason", "next_attempt_at", "updated_at",
        "application_id", "workspace_id", "scope_version",
    }
    return first.model_dump(exclude=immutable) == second.model_dump(exclude=immutable)


def _source_refs(record):
    if hasattr(record, "sources"):
        sources = record.sources
    else:
        sources = (record,)
    return [
        {
            "conversation_id": str(source.source_conversation_id),
            "turn_id": str(source.source_turn_id),
            "user_message_ids": [str(identifier) for identifier in source.source_message_ids],
            "source_fingerprint": source.source_fingerprint,
        }
        for source in sources
    ]


def _record_fingerprint(record) -> str:
    encoded = record.model_dump_json(exclude_none=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _chunks(values):
    values = tuple(values)
    return [values[index : index + SUMMARY_CHUNK_IDS] for index in range(0, len(values), SUMMARY_CHUNK_IDS)]


def _chunk_manifest(chunks):
    hashes = [hashlib.sha256(_json([str(identifier) for identifier in chunk]).encode()).hexdigest()
              for chunk in chunks]
    flattened = tuple(identifier for chunk in chunks for identifier in chunk)
    return {"chunks": len(chunks), "count": len(flattened), "hashes": hashes,
            "sha256": _sequence_hash(flattened)}


def _sequence_hash(values):
    return hashlib.sha256(_json([str(identifier) for identifier in values]).encode()).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _timestamp(value: datetime) -> str:
    value = _utc(value)
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp_invalid")
    return value.astimezone(UTC)


def _marshal(value: dict[str, Any]):
    from boto3.dynamodb.types import TypeSerializer

    serializer = TypeSerializer()
    return {key: serializer.serialize(item) for key, item in value.items()}


def _unmarshal(value: dict[str, Any]):
    from boto3.dynamodb.types import TypeDeserializer

    deserializer = TypeDeserializer()
    return {key: deserializer.deserialize(item) for key, item in value.items()}


def _put(item, *, condition: str | None = None):
    if _item_size(item) > MAX_DYNAMO_ITEM_BYTES:
        raise StorageUnavailableError("dynamodb item too large")
    request = {"TableName": "", "Item": _marshal(item)}
    # TableName is filled by DynamoDBRuntimeTable.transact.
    if condition:
        request["ConditionExpression"] = condition
    return {"Put": request}


def _update(
    key,
    update_expression,
    *,
    names,
    values,
    condition,
    more_names=None,
    more_values=None,
):
    merged_names = {**names, **(more_names or {})}
    merged_values = {**values, **(more_values or {})}
    return {"Update": {
        "TableName": "",
        "Key": _marshal(key),
        "UpdateExpression": update_expression,
        "ConditionExpression": condition,
        "ExpressionAttributeNames": merged_names,
        "ExpressionAttributeValues": _marshal(merged_values),
    }}


def _delete(key):
    return {"Delete": {"TableName": "", "Key": _marshal(key)}}


def _operation_size(operation):
    raw = json.dumps(operation, separators=(",", ":"), ensure_ascii=True)
    return len(raw.encode("utf-8")) + 64


def _item_size(item):
    raw = json.dumps(item, default=str, ensure_ascii=False, separators=(",", ":"))
    # Account for DynamoDB's per-attribute name/type overhead conservatively.
    return len(raw.encode("utf-8")) + 16 * len(item)


def _conditional_failure(error: Exception) -> bool:
    response = getattr(error, "response", {})
    code = response.get("Error", {}).get("Code", "")
    if code == "ConditionalCheckFailedException":
        return True
    if code == "TransactionCanceledException":
        reasons = response.get("CancellationReasons", ())
        return not reasons or any(reason.get("Code") == "ConditionalCheckFailed" for reason in reasons)
    return error.__class__.__name__ in {"ConditionalCheckFailedException", "TransactionCanceledException"}
