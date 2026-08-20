# Phase 1 API contract

This document defines the HTTP boundary before the conversation routes are
implemented. All `/v1` routes operate for the current logical Phase 1 owner,
`local`; they are not authenticated.

## Conventions

- Resource IDs are UUIDs. Malformed UUIDs and resources unavailable to the
  current owner return a consistent 4xx response.
- Timestamps are UTC ISO 8601 values.
- Requests reject unknown fields. Responses never include provider keys,
  internal exception traces, or unbounded provider output.
- Conversation lists are newest first. A conversation detail response contains
  only its active message branch; superseded records remain auditable in
  persistence.

## Routes

| Method | Route | Request body | Response |
| --- | --- | --- | --- |
| `GET` | `/health` | — | Existing readiness response: `{"status":"ok","service":"api"}` |
| `POST` | `/v1/conversations` | Optional `title` | A `Conversation` |
| `GET` | `/v1/conversations` | — | `{"conversations": [Conversation]}` |
| `GET` | `/v1/conversations/{conversation_id}` | — | `{"conversation": Conversation, "messages": [Message]}` |
| `POST` | `/v1/conversations/{conversation_id}/messages` | `{"content": "..."}` | SSE stream |
| `POST` | `/v1/conversations/{conversation_id}/messages/{message_id}/regenerate` | — | SSE stream replacing a completed assistant message |
| `POST` | `/v1/conversations/{conversation_id}/messages/{message_id}/edit-and-retry` | `{"content": "..."}` | SSE stream after replacing a user message |

`Conversation` fields are `id`, `owner_id`, `title`, `created_at`, and
`updated_at`. `Message` fields are `id`, `conversation_id`, `owner_id`,
`role` (`user` or `assistant`), `content`, `status` (`streaming`,
`completed`, `failed`, or `superseded`), `created_at`, `parent_message_id`,
`supersedes_message_id`, `model`, and `error_code`.

Titles may be derived deterministically from the first user message. Phase 1
does not make a model call to create titles.

## Server-sent events

Each streamed endpoint returns `text/event-stream`. Every event has an `event:`
name and JSON `data:` payload.

| Event | JSON payload |
| --- | --- |
| `message.created` | `{"message": Message}` for each persisted user or assistant message |
| `response.delta` | `{"message_id": "UUID", "delta": "incremental text"}` |
| `response.completed` | `{"message": Message}` for the final persisted assistant message |
| `response.error` | `{"message_id": "UUID", "code": "stable_error_code", "message": "safe user-facing text"}` |

An error event is safe for display. It must not contain provider credentials,
internal exception details, or raw upstream output.
