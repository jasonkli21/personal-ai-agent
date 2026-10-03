"""Shared branch selection rules for durable and in-memory message repositories."""

from collections.abc import Sequence
from uuid import UUID

from personal_ai.entities import Message, MessageStatus


def effective_message(message: Message, by_id: dict[UUID, Message]) -> Message:
    """Apply a durable root cut without rewriting every historical descendant."""
    current = message
    seen: set[UUID] = set()
    while current.id not in seen:
        seen.add(current.id)
        if current.status is MessageStatus.SUPERSEDED:
            return message.model_copy(update={"status": MessageStatus.SUPERSEDED})
        parent = by_id.get(current.parent_message_id)
        if (
            parent is None
            or parent.owner_id != message.owner_id
            or parent.conversation_id != message.conversation_id
        ):
            break
        current = parent
    return message


def descendant_ids(messages: Sequence[Message], root_id: UUID) -> set[UUID]:
    """Return a message and every child in its historical branch."""
    children: dict[UUID, list[UUID]] = {}
    for message in messages:
        if message.parent_message_id is not None:
            children.setdefault(message.parent_message_id, []).append(message.id)
    found = {root_id}
    pending = [root_id]
    while pending:
        for child in children.get(pending.pop(), ()):
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


def active_path(messages: Sequence[Message]) -> list[Message]:
    """Choose the newest intact leaf, excluding cut, missing, or cyclic ancestry.

    Memoize ancestry validity so long conversations do not traverse the same
    prefix once per message. Invalid stored links never enter model context.
    """
    by_id = {message.id: message for message in messages}
    valid: dict[UUID, bool] = {}
    for message in messages:
        current = message
        path: list[UUID] = []
        seen: set[UUID] = set()
        while current.id not in valid:
            if current.id in seen or current.status is MessageStatus.SUPERSEDED:
                eligible = False
                break
            path.append(current.id)
            seen.add(current.id)
            if current.parent_message_id is None:
                eligible = True
                break
            parent = by_id.get(current.parent_message_id)
            if (
                parent is None
                or parent.owner_id != current.owner_id
                or parent.conversation_id != current.conversation_id
            ):
                eligible = False
                break
            current = parent
        else:
            eligible = valid[current.id]
        for identifier in path:
            valid[identifier] = eligible
        # A superseded starting record has an empty path and still needs caching.
        valid[message.id] = eligible

    viable = {identifier: by_id[identifier] for identifier, eligible in valid.items() if eligible}
    parents = {message.parent_message_id for message in viable.values()}
    leaves = [message for message in viable.values() if message.id not in parents]
    if not leaves:
        return []
    leaf = max(leaves, key=lambda item: (item.created_at, str(item.id)))
    path: list[Message] = []
    while True:
        path.append(leaf)
        if leaf.parent_message_id is None:
            return list(reversed(path))
        leaf = viable[leaf.parent_message_id]
