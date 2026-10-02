# API contract (Phases 1–6)

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

## Phase 3 memory amendments (2026-10-02)

Successful chat/SSE responses remain unchanged. After the user/branch mutation,
optional owner-scoped memory retrieval precedes context assembly; retrieval and
memory-counting failure continue with the valid Phase 2 request. Extraction runs
after final completion persistence and the terminal frame, with no additional SSE
messages or user-facing extraction errors.

The gated context endpoint optionally accepts up to 20 repeated `memory_ids=UUID`
query parameters. Both `CONTEXT_INSPECTION_ENABLED` and `MEMORY_INSPECTION_ENABLED`
are required for this extension in backend and proxy. It reports supplied-record
planning metadata in `memory`: `mode`, aggregate `tokens`, `diagnostics`, and
`records` with `id`, `type`, `source_conversation_id`, `source_message_ids`,
`observed_at`, `effective_at`, `created_at`, `selected`, `reason`,
`estimated_tokens`, and null `similarity`. It performs no embedding or semantic
query and makes no prior-use claim. Memory text and vectors are omitted. A missing
or foreign record returns 404; malformed or oversized ID lists return 422.
There are no user-facing memory create/edit/delete/list routes in Phase 3.

## Phase 4 lifecycle amendments (2026-10-02)

Public chat/SSE contracts remain unchanged. The supplied-ID inspector also accepts
`MEMORY_LIFECYCLE_INSPECTION_ENABLED` with the existing context gate; corresponding
frontend/proxy gates are required. Metadata adds requested/applied variants, policy
version/identity, lifecycle statuses, event IDs and safe reasons, per-source IDs and
score components. Overall score and similarity remain null without query relevance;
selection means estimated fit. Content/vectors and mutation operations remain absent.

The public API has no `/tasks/research` or `/tasks/memory` route. The private
`personal_ai.worker:app` exposes `/tasks/memory` for authenticated Pub/Sub push only
under Cloud Run IAM; it decodes a bounded envelope containing a job ID/schema version
and obtains owner/source authority from durable storage. Disabled/completed/terminal
work returns 204; active leases and retryable processing return 503. See the
[Phase 4 guide](phase-4-implementation-guide.md) for gates and failure recovery.

## Phase 5 standalone research (`research-v1`)

All routes require `RESEARCH_ENABLED`; disabled routes return safe 404 before
constructing storage/provider clients. The temporary `local` owner is not
identity or authentication. Browser requests go through Next.js `/api/research`.

| Route | Contract |
| --- | --- |
| `POST /v1/research` | `{schema_version?:"research-v1", question:string (1–500 characters), freshness?:"general"\|"current", idempotency_key:UUID}`; returns 201 session, including on replay |
| `GET /v1/research/{UUID}` | Owner-scoped session detail, result/excerpts, citations and provenance; stale answers are withheld |
| `POST /v1/research/{UUID}/run` | Empty request; atomically claims and streams once; running returns 409; terminal replay sends one terminal event without tools |
| `GET /v1/research/{UUID}/inspection` | Requires separate inspection gate; read-only counts, selection scores/exclusions and duplicate metadata; no query/passages/provider calls |

Session states are `pending`, `running`, `completed`, `insufficient`, `failed`,
`expired`. Detail includes typed `request`, `queries`, `attempts`, `observations`,
`evidence`, `selection`, `answer`, and `citations`; each nested record preserves
owner/session correlation. The internal execution token is excluded from wire
responses. A reused key with different normalized input returns 409
`idempotency_conflict`. Validation errors return 422; foreign/missing IDs 404;
storage failures 503. HTTP errors use the existing safe error envelope.

Research SSE uses its own event names; every payload includes
`schema_version:"research-v1"` and `session_id`. Events follow durable persistence:

| Event | Additional fields |
| --- | --- |
| `research.started` | `state:"running"` |
| `research.planned` | `query_count` |
| `research.attempt` | `query_id`, `attempt_id`, `state:"completed"\|"failed"` (bounded retries may repeat) |
| `research.evidence` | `source_count`, `evidence_count` |
| `research.selected` | `evidence_count` |
| `research.terminal` | `state`, `failure_code` nullable; fetch detail for the durable result |

No raw deltas, questions or external text are streamed. Missing terminal frames
must be treated as interrupted, followed by a detail read. Cancellation fails the
session; process loss derives `execution_abandoned` after its recorded deadline.
Existing chat SSE events remain unchanged. The result is validated literal source
excerpts with adjacent numbered citations, not unrestricted factual synthesis.
Each citation exposes original normalized URL, optional title, observation time,
evidence expiry and source/evidence IDs. Known old publication dates are excluded;
missing dates remain unknown. See [Phase 5 plan](phase-5-implementation-plan.md).

## Phase 6 decision support (`decision-v1`)

Decision routes require `DECISION_ENABLED`; inspection additionally requires
`DECISION_INSPECTION_ENABLED`. Browser calls pass through the Next.js
`/api/decisions` proxy. Both backend gates and frontend gates default off.
The temporary `local` owner is not identity or authentication.

| Route | Contract |
| --- | --- |
| `POST /v1/decisions` | Validated candidate proposals, typed constraints/preferences, an idempotency key, and exactly one evidence path: a completed Phase 5 `research_session_id` or explicitly supplied source references and fingerprint-checked excerpts. Returns 201 `DecisionResult`. |
| `GET /v1/decisions/{UUID}` | Owner-scoped immutable result, evidence snapshot, entities, claims, resolution matches, and candidate evaluations. |
| `GET /v1/decisions/{UUID}/inspection` | Requires both decision and inspection gates; read-only selected/excluded evaluations, attribute and constraint outcomes, score components, policy versions, resolution trace, and source links. No raw memory or hidden model reasoning. |

The response distinguishes `recommended`, `eligible_unranked`,
`research_needed`, and `no_verified_match`. Every selected result has eligible
candidate, claim, and exact evidence-reference provenance. Unknown, stale,
conflicting, unverified, or unsupported required values do not pass hard
constraints. Currency conversion is not guessed. Preferences only rank eligible
candidates; a ranking failure retains the eligible set without a score or rank.
Decision snapshots are append-only and include the evidence metadata and
versioned identity, constraint, ranking, and evidence-snapshot policies.

Malformed inputs return 422; missing or foreign-owner records return 404;
idempotency conflicts and unusable evidence return safe 409/422 responses;
storage failures return 503. The decision result page presents supported claim
values, observation/expiry times, requirement outcomes, and source links. The
development inspector is separately gated and read-only. See the
[Phase 6 guide](phase-6-implementation-guide.md) and
[decision-support ADR](decisions/0012-evidence-grounded-decision-support.md).
