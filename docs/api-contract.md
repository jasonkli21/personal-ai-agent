# Conversation API contract (Phases 1–2)

This document defines the implemented HTTP boundary. All `/v1` routes operate
for the current logical owner,
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
| `GET` | `/v1/conversations/{conversation_id}/context` | — | Development-only read-only selection report; 404 when disabled |
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

Phase 2 preparation has two atomic persistence stages: persist the user/branch
mutation and reserve the conversation, then assemble/count/refresh context before
creating an assistant placeholder and releasing that reservation. Preparation
failure leaves an auditable completed user without a misleading streaming
assistant. Regenerate supersedes its previous response before assembling its
retained prefix; edit/retry preserves old records as superseded audit history.

Concurrent mutations, preparation reservations, or an active response return
HTTP 409 with `conversation_busy`. Expired reservations and streaming
placeholders recover on the next mutation after the configured provider timeout
plus 60 seconds. Late requests cannot release a new reservation or overwrite a
terminal assistant status.

Before streaming, mandatory overflow returns HTTP 422 `context_message_too_large`;
invalid operator configuration returns HTTP 503 `context_budget_invalid`, and
provider counting failure returns a safe HTTP 503 provider code. The persisted
user remains editable. Summary refresh failure falls back to smaller recent
context when it fits. Successful SSE event names/order remain unchanged.

The inspector reconstructs the latest completed user's possible input. It
reports capacity/reserves/margins, selected/excluded metadata and reasons,
summary provenance, aggregate estimated token counts, diagnostics, and overflow.
It never invokes a provider or changes storage/timestamps. It omits raw content,
settings secrets, and provider objects; normal deployments return 404.

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

## Phase 2 review amendments (2026-10-02)

Supersession is represented by durable root cuts. Repository reads return
`superseded` for every historical descendant, while original descendant documents
retain content, links, and terminal status. This is compatible with existing eager
supersession records and leaves successful SSE payloads unchanged.

Context inspection includes `coverage_message_ids`, `coverage_fingerprint`, and
`skipped_message_ids` alongside summary source provenance. Only complete source
turns enter summary generation; skipped incomplete turns remain covered for branch
validation. Legacy summaries omit explicit coverage and require a complete prefix.
Preparation counting and generation share `REQUEST_TIMEOUT_SECONDS`; expiration
returns the safe `llm_timeout` envelope before streaming.
