"""Offline contract tests for the Phase 1 conversation repositories."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from personal_ai.entities import Conversation, Message, MessageRole, MessageStatus
from personal_ai.storage import (
    ConversationConflictError,
    InMemoryConversationRepository,
    InMemoryMessageRepository,
    ResourceNotFoundError,
)

OWNER = "local"
OTHER_OWNER = "someone-else"
BASE_TIME = datetime(2026, 8, 19, tzinfo=UTC)


def conversation(identifier: int, *, owner_id: str = OWNER, offset: int = 0) -> Conversation:
    instant = BASE_TIME + timedelta(seconds=offset)
    return Conversation(
        id=UUID(int=identifier),
        owner_id=owner_id,
        scope_version=2,
        title=f"Conversation {identifier}",
        created_at=instant,
        updated_at=instant,
    )


def message(
    identifier: int,
    conversation_id: UUID,
    *,
    owner_id: str = OWNER,
    parent_message_id: UUID | None = None,
    status: MessageStatus = MessageStatus.COMPLETED,
    offset: int = 0,
) -> Message:
    return Message(
        id=UUID(int=identifier),
        conversation_id=conversation_id,
        owner_id=owner_id,
        scope_version=2,
        role=MessageRole.USER if identifier % 2 else MessageRole.ASSISTANT,
        content=f"message {identifier}",
        status=status,
        created_at=BASE_TIME + timedelta(seconds=offset),
        parent_message_id=parent_message_id,
    )


def test_conversations_are_created_listed_newest_first_and_owner_scoped() -> None:
    repository = InMemoryConversationRepository()
    oldest = conversation(1, offset=1)
    newest = conversation(2, offset=2)
    private = conversation(3, owner_id=OTHER_OWNER, offset=3)
    for item in (oldest, newest, private):
        repository.create(item)

    assert repository.get(owner_id=OWNER, conversation_id=oldest.id) == oldest
    assert repository.list(owner_id=OWNER) == [newest, oldest]
    with pytest.raises(ResourceNotFoundError):
        repository.get(owner_id=OTHER_OWNER, conversation_id=oldest.id)


def test_message_add_and_finalize_touch_the_parent_conversation() -> None:
    conversations = InMemoryConversationRepository()
    stored_conversation = conversation(1)
    conversations.create(stored_conversation)
    messages = InMemoryMessageRepository(conversations)
    first = message(2, stored_conversation.id, status=MessageStatus.STREAMING, offset=5)

    messages.create(first)
    assert (
        conversations.get(owner_id=OWNER, conversation_id=stored_conversation.id).updated_at
        == first.created_at
    )

    finalized_at = BASE_TIME + timedelta(seconds=10)
    finalized = messages.update_status(
        owner_id=OWNER,
        conversation_id=stored_conversation.id,
        message_id=first.id,
        status=MessageStatus.COMPLETED,
        content="finished",
        updated_at=finalized_at,
    )
    assert finalized.status is MessageStatus.COMPLETED
    assert finalized.content == "finished"
    assert (
        conversations.get(owner_id=OWNER, conversation_id=stored_conversation.id).updated_at
        == finalized_at
    )


def test_active_messages_are_chronological_and_old_branches_are_preserved() -> None:
    conversations = InMemoryConversationRepository()
    stored_conversation = conversation(1)
    conversations.create(stored_conversation)
    repository = InMemoryMessageRepository(conversations)
    user = message(2, stored_conversation.id, offset=1)
    old_reply = message(3, stored_conversation.id, parent_message_id=user.id, offset=2)
    replacement = message(4, stored_conversation.id, parent_message_id=user.id, offset=3)
    for item in (user, old_reply, replacement):
        repository.create(item)

    superseded = repository.supersede_path(
        owner_id=OWNER,
        conversation_id=stored_conversation.id,
        message_id=old_reply.id,
        updated_at=BASE_TIME + timedelta(seconds=4),
    )

    assert [item.id for item in superseded] == [old_reply.id]
    assert (
        repository.get(
            owner_id=OWNER, conversation_id=stored_conversation.id, message_id=old_reply.id
        ).status
        is MessageStatus.SUPERSEDED
    )
    assert [
        item.id
        for item in repository.list_active(owner_id=OWNER, conversation_id=stored_conversation.id)
    ] == [user.id, replacement.id]


def test_editing_an_earlier_message_supersedes_only_its_historical_path() -> None:
    repository = InMemoryMessageRepository()
    conversation_id = UUID(int=100)
    first = message(1, conversation_id, offset=1)
    answer = message(2, conversation_id, parent_message_id=first.id, offset=2)
    unrelated_root = message(3, conversation_id, offset=3)
    for item in (first, answer, unrelated_root):
        repository.create(item)

    repository.supersede_path(
        owner_id=OWNER,
        conversation_id=conversation_id,
        message_id=first.id,
        updated_at=BASE_TIME + timedelta(seconds=4),
    )

    assert (
        repository.get(owner_id=OWNER, conversation_id=conversation_id, message_id=first.id).status
        is MessageStatus.SUPERSEDED
    )
    assert (
        repository.get(owner_id=OWNER, conversation_id=conversation_id, message_id=answer.id).status
        is MessageStatus.SUPERSEDED
    )
    assert (
        repository.get(
            owner_id=OWNER, conversation_id=conversation_id, message_id=unrelated_root.id
        ).status
        is MessageStatus.COMPLETED
    )
    assert repository.list_active(owner_id=OWNER, conversation_id=conversation_id) == [
        unrelated_root
    ]


def test_message_lookup_hides_records_owned_by_someone_else() -> None:
    repository = InMemoryMessageRepository()
    conversation_id = UUID(int=100)
    stored = message(1, conversation_id, owner_id=OTHER_OWNER)
    repository.create(stored)

    with pytest.raises(ResourceNotFoundError):
        repository.get(owner_id=OWNER, conversation_id=conversation_id, message_id=stored.id)


def test_prepare_message_turn_supersedes_and_creates_replacement_atomically() -> None:
    conversations = InMemoryConversationRepository()
    stored_conversation = conversation(200)
    conversations.create(stored_conversation)
    repository = InMemoryMessageRepository(conversations)
    user = message(201, stored_conversation.id, offset=1)
    old_answer = message(202, stored_conversation.id, parent_message_id=user.id, offset=2)
    repository.create(user)
    repository.create(old_answer)
    replacement = Message(
        id=UUID(int=203), conversation_id=stored_conversation.id, owner_id=OWNER,
        scope_version=2,
        role=MessageRole.ASSISTANT, content="", status=MessageStatus.STREAMING,
        created_at=BASE_TIME + timedelta(seconds=3), parent_message_id=user.id,
        supersedes_message_id=old_answer.id,
    )

    prepared = repository.prepare_message_turn(
        owner_id=OWNER,
        conversation_id=stored_conversation.id,
        expected_active_ids=[user.id, old_answer.id],
        supersede_from_message_id=old_answer.id,
        messages=[replacement],
        updated_at=BASE_TIME + timedelta(seconds=3),
    )

    assert prepared == [replacement]
    assert repository.get(
        owner_id=OWNER, conversation_id=stored_conversation.id, message_id=old_answer.id
    ).status is MessageStatus.SUPERSEDED
    assert repository.list_active(owner_id=OWNER, conversation_id=stored_conversation.id) == [
        user, replacement
    ]


def test_failed_turn_preparation_preserves_active_branch_and_creates_nothing() -> None:
    conversation_id = UUID(int=210)
    repository = InMemoryMessageRepository()
    user = message(211, conversation_id, offset=1)
    old_answer = message(212, conversation_id, parent_message_id=user.id, offset=2)
    repository.create(user)
    repository.create(old_answer)
    replacement = Message(
        id=UUID(int=213), conversation_id=conversation_id, owner_id=OWNER,
        scope_version=2,
        role=MessageRole.ASSISTANT, content="", status=MessageStatus.STREAMING,
        created_at=BASE_TIME + timedelta(seconds=3), parent_message_id=user.id,
        supersedes_message_id=old_answer.id,
    )

    with pytest.raises(ConversationConflictError):
        repository.prepare_message_turn(
            owner_id=OWNER,
            conversation_id=conversation_id,
            expected_active_ids=[user.id],
            supersede_from_message_id=old_answer.id,
            messages=[replacement],
            updated_at=BASE_TIME + timedelta(seconds=3),
        )

    assert repository.list_active(owner_id=OWNER, conversation_id=conversation_id) == [
        user, old_answer
    ]
    with pytest.raises(ResourceNotFoundError):
        repository.get(owner_id=OWNER, conversation_id=conversation_id, message_id=replacement.id)


def test_turn_preparation_rejects_an_active_stream_and_status_update_is_conditional() -> None:
    conversation_id = UUID(int=220)
    repository = InMemoryMessageRepository()
    user = message(221, conversation_id, offset=1)
    streaming = message(
        222, conversation_id, parent_message_id=user.id,
        status=MessageStatus.STREAMING, offset=2,
    )
    repository.create(user)
    repository.create(streaming)
    next_user = message(223, conversation_id, parent_message_id=streaming.id, offset=3)

    with pytest.raises(ConversationConflictError):
        repository.prepare_message_turn(
            owner_id=OWNER,
            conversation_id=conversation_id,
            expected_active_ids=[user.id, streaming.id],
            supersede_from_message_id=None,
            messages=[next_user],
            updated_at=BASE_TIME + timedelta(seconds=3),
        )

    assert repository.update_status(
        owner_id=OWNER,
        conversation_id=conversation_id,
        message_id=streaming.id,
        status=MessageStatus.COMPLETED,
        content="late response",
        updated_at=BASE_TIME + timedelta(seconds=4),
        expected_status=MessageStatus.COMPLETED,
    ) is None
    assert repository.get(
        owner_id=OWNER, conversation_id=conversation_id, message_id=streaming.id
    ).status is MessageStatus.STREAMING


def test_active_path_excludes_cycles_missing_parents_and_foreign_ancestry() -> None:
    from personal_ai.storage.branches import active_path

    conversation_id = UUID(int=300)
    root = message(301, conversation_id, offset=1)
    answer = message(302, conversation_id, parent_message_id=root.id, offset=2)
    cycle = message(303, conversation_id, parent_message_id=UUID(int=304), offset=3)
    cycle_parent = message(304, conversation_id, parent_message_id=cycle.id, offset=4)
    cycle_child = message(305, conversation_id, parent_message_id=cycle.id, offset=5)
    orphan = message(306, conversation_id, parent_message_id=UUID(int=999), offset=6)
    foreign = message(307, conversation_id, owner_id=OTHER_OWNER, offset=7)
    foreign_child = message(308, conversation_id, parent_message_id=foreign.id, offset=8)

    assert active_path([
        root, answer, cycle, cycle_parent, cycle_child, orphan, foreign_child,
    ]) == [root, answer]
    assert active_path([root, answer, foreign, foreign_child]) == [foreign]
    assert active_path([cycle, cycle_parent, cycle_child]) == []


def test_active_path_handles_long_unordered_history_without_recursive_traversal() -> None:
    from personal_ai.storage.branches import active_path

    conversation_id = UUID(int=400)
    history = [
        message(
            1000 + i,
            conversation_id,
            parent_message_id=UUID(int=999 + i) if i else None,
            offset=i,
        )
        for i in range(6000)
    ]
    assert active_path(list(reversed(history))) == history
