# API contract (Phases 1–14 local implementation)

This document defines the implemented HTTP boundary. All `/v1` routes require an application principal. Staging/production verify
Google OIDC and resolve an opaque owner from issuer and stable subject; client
payloads cannot select an owner. Local/test development explicitly uses the
unauthenticated `local` principal. Cloud Run service IAM is an additional
web-to-API boundary. See the [authorization matrix](phase-9-authorization-matrix.md).

## Conventions

- Resource IDs are UUIDs. Malformed UUIDs and resources unavailable to the
  current owner return a consistent 4xx response.
- Timestamps are UTC ISO 8601 values.
- Requests reject unknown fields. Responses never include provider keys,
  internal exception traces, or unbounded provider output.
- Conversation lists return the newest 50 records; the current API has no cursor pagination. A conversation detail response contains
  only its active message branch; superseded records remain auditable in
  persistence.

## Routes

| Method | Route | Request body | Response |
| --- | --- | --- | --- |
| `GET` | `/health` | — | Existing readiness response: `{"status":"ok","service":"api"}` |
| `GET` | `/v1/profile` | — | Sparse owner-wide `GlobalProfile` |
| `PUT` | `/v1/profile` | `GlobalProfileUpdate` with explicit values and per-field application sharing | Updated sparse owner-wide `GlobalProfile` |
| `POST` | `/v1/conversations` | Optional `title` | A `Conversation` |
| `GET` | `/v1/conversations` | — | `{"conversations": [Conversation]}` |
| `GET` | `/v1/conversations/{conversation_id}` | — | `{"conversation": Conversation, "messages": [Message]}` |
| `GET` | `/v1/conversations/{conversation_id}/context` | Optional repeated `memory_ids=UUID` | Development-only read-only estimate plus a retained actual-build trace for the latest user turn, when available; 404 when disabled |
| `POST` | `/v1/conversations/{conversation_id}/messages` | `{"content": "..."}` | SSE stream |
| `POST` | `/v1/conversations/{conversation_id}/messages/{message_id}/regenerate` | — | SSE stream replacing a completed assistant message |
| `POST` | `/v1/conversations/{conversation_id}/messages/{message_id}/edit-and-retry` | `{"content": "..."}` | SSE stream after replacing a user message |

## Phase 11–12 owner profile and context building

`/v1/profile` is owner-scoped through the application principal and requires
the standalone `personal_ai` application scope with no workspace. Deployed
requests use the verified owner principal; local/test requests use the fixed
development owner. Other application scopes receive 404. The profile is sparse
and AI-owned; it accepts only explicit
user-set fields: `preferred_units` (`metric` or `imperial`), `locale`,
`response_style` (`concise`, `balanced`, or `detailed`), and `answer_length`
(`short`, `standard`, or `expanded`). Each update field has a
`shared_with_applications` list; omitted values remain absent. `remove_fields`
removes selected fields. Responses include field-level `set_by: "user"` and
`set_at` provenance plus a monotonically increasing profile revision.

The `global_profile` context provider returns only fields selected by the
caller and explicitly shared with the current application. The typed context
provider interfaces also expose bounded selections and normalized items for
conversation, memory, external evidence, client context, and registered
read-only tool results. The shared Phase 12 builder fits the conversation,
memory, and explicitly selected provider items under global and per-source
budgets, rechecks expiry and permission dependencies, preserves source
authority and sensitivity, and produces a metadata-only manifest for the
messages actually built. Sources remain caller-selected; deterministic
automatic planning is Phase 13 scope. The development inspector reports an
estimated current view and does not claim historical prompt reconstruction.
See the [Phase 11 guide](personal-ai-chapter-2/phase-11-implementation-guide.md),
[Phase 12 guide](personal-ai-chapter-2/phase-12-implementation-guide.md), and
[Phase 12 evidence](personal-ai-chapter-2/phase-12-implementation-evidence.md).

### Proposed upstream itinerary proposal (pending independent review)

This branch contains a separately versioned proposal capability for review;
the route below is **not yet an accepted inter-repository contract**. Travel
consumers must not depend on it until the coordinator accepts and pins a
reviewed upstream revision. Its normative proposed schema, limits, examples,
gates, and lifecycle are in [itinerary-proposal-contract.md](itinerary-proposal-contract.md).

| Method | Proposed route | Request body | Response |
| --- | --- | --- | --- |
| `POST` | `/v1/travel/itinerary-proposals` | `itinerary-proposal-v1` with a bounded typed trip projection and separate instruction | Immutable owner-scoped result; local fake mode is credential-free |
| `GET` | `/v1/travel/itinerary-proposals/{proposal_id}` | — | The same immutable result for reconciliation |
| `GET` | `/v1/travel/itinerary-proposals/by-key/{idempotency_key}` | — | Owner-scoped lookup for lost-POST reconciliation |

The feature gate defaults off. It returns only typed operations over
request-scoped opaque handles; it neither reads nor changes travel database
state. The consumer must revalidate against current SQL state and retain
preview/apply authority.

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

The inspector reconstructs the latest completed user's possible input and labels
that report `estimated_current_view`. For a matching retained trace it also
returns a separate `actual_build` record captured during that turn's preparation;
it does not infer a past build from current state. Actual traces include request,
conversation, and turn IDs, planner/policy/source-version labels, source selection
and exclusion decisions, authority/sensitivity, bounded token counts and reasons.
Provider-supplied source and item identifiers are fingerprinted before storage;
prompts, provider values, credentials, and hidden reasoning are omitted. The
system retains at most 32 traces per conversation, with a 48 KiB serialized
payload ceiling per trace. Missing or expired traces return `manifest_missing`
and leave the estimate explicitly labeled. The inspector performs no provider
calls, writes, or retention actions; normal deployments return 404.

The development inspector sends an `X-Request-ID`; the proxy forwards the
validated ID and returns the API correlation header. The actual trace separately
shows the correlation ID from the generation request that built that context.

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
constructing storage/provider clients. The local/test `local` owner is not
identity or authentication; deployed requests follow the principal boundary above. Browser requests go through Next.js `/api/research`.

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

## Booking document extraction candidate (`booking-document-extraction-v1`)

The bounded local implementation is described by the
[candidate contract](booking-document-extraction-contract.md) and [ADR 0020](decisions/0020-booking-document-extraction.md).
Both `BOOKING_EXTRACTIONS_ENABLED` and `BOOKING_EXTRACTION_PROVIDER_ENABLED`
default off. The route requires a verified owner outside local/test development,
explicit submit consent, an owner-scoped UUID idempotency key, and a source hash
matching at most 200,000 characters of extracted text. The special route body
limit is 1,300,000 bytes; ordinary API JSON limits are unchanged.

`POST /v1/travel/booking-extractions` returns no more than ten uncertain typed
candidates with bounded literal source spans. `GET /{UUID}` and
`GET /by-key/{UUID}` recover the same owner/key result. `DELETE /{UUID}` removes
candidate details; `DELETE /by-key/{UUID}` accepts the expected
`source_sha256` and can install a deletion tombstone before a late POST. Both
retain only a short-lived idempotency tombstone. Raw
document text is ephemeral and never stored in Firestore. Fake generation
requires `synthetic_fixture: true` and is restricted to local/test
environments; real Gemini inference requires Google OIDC even in a local app
environment. One elapsed deadline bounds body receipt, claim, inference, and
terminal storage. Result DTOs enforce bounded expiry, unique evidence spans,
literal field evidence, explicit uncertainty, and empty candidates for
non-completed states. The candidate is not yet accepted for cross-repository
private-data use; model/provider data-use review, live identity/IAM, Firestore
TTL and coordinator whole-phase verification remain open.

## Phase 6 decision support (`decision-v1`)

Decision routes require `DECISION_ENABLED`; inspection additionally requires
`DECISION_INSPECTION_ENABLED`. Browser calls pass through the Next.js
`/api/decisions` proxy. Both backend gates and frontend gates default off.
Local/test `local` ownership is not authentication; deployed requests follow the principal boundary above.

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

## Phase 7 domain comparisons (`domain-module-v1`)

Every domain route requires both `DECISION_ENABLED` and its domain-specific
backend gate (`TRAVEL_ENABLED` or `SHOPPING_ENABLED`). The Next.js proxy
enforces the same server-side gates; direct browser-to-API calls are not used.
`GET /v1/domains` lists only enabled modules. The local/test `local` owner remains
unauthenticated; deployed requests require the principal boundary above.

| Route | Contract |
| --- | --- |
| `GET /v1/domains/{domain}/fixtures` | Lists bounded synthetic examples (`travel` or `shopping`). |
| `POST /v1/domains/{domain}/lookup` | `domain-lookup-v1`: idempotency key, one bounded query, optional shared hard constraints/preferences, and result limit. Travel accepts a place query; shopping accepts an exact 8–14 digit barcode. Returns a saved comparison. |
| `POST /v1/domains/{domain}/comparisons` | `domain-comparison-v1`: a Phase 6 decision request plus provider-observation extensions correlated to its evidence. |
| `POST /v1/domains/{domain}/fixtures/{fixture_id}/compare` | Runs one deterministic synthetic decision fixture through the shared platform. |
| `GET /v1/domains/{domain}/comparisons/{id}` | Returns the immutable comparison snapshot, registered field schema, core decision evidence/results, provider observations, and typed domain claim extensions. |
| `GET /v1/domains/{domain}/comparisons/{id}/inspection` | Requires `DOMAIN_INSPECTION_ENABLED`; returns read-only source-policy and ID metadata, not raw private memory or hidden reasoning. |

The comparison snapshot records the shared constraints and preferences,
candidate IDs/order, result state, source links, freshness/conflict/missing
statuses, rationale, and shared/domain policy versions. Local UI filters do not
write a decision or rerun a provider. Malformed input returns 422; unavailable
or disabled domain/comparison IDs return 404; provider, idempotency, and storage
errors use bounded safe error codes.

`TRAVEL_PLACES_ADAPTER=osm_nominatim` supports one user-submitted place or area
lookup per request, with a Firestore-shared one-request-per-second limiter,
application User-Agent/contact, seven-day place TTL, OSM attribution, and an
explicit notice that submitted text goes to the provider. It does not provide
autocomplete, bulk lookup, lodging, or current availability.
`SHOPPING_PRODUCTS_ADAPTER=open_food_facts` supports exact barcode lookup,
requests only bounded product identity fields, shares a Firestore rate record
with a four-second minimum interval, and uses a thirty-day catalog TTL. It does
not provide merchant offers, stock, shipping, or delivery. Both adapters and
their policy-approval gates default off; adapter policy links and setup are in
the [Phase 7 guide](phase-7-implementation-guide.md) and
[ADRs](decisions/0013-nominatim-travel-place-source.md).

## Phase 8 iterative research (`iterative-research-v1`)

Iterative research requires `RESEARCH_ENABLED`, `ITERATIVE_RESEARCH_ENABLED`,
and `ITERATIVE_PROGRESS_ENABLED`. All three gates default off. The ordinary
single-pass `POST /v1/research/{UUID}/run` remains the default path and its
`research-v1` SSE contract is unchanged. A decision intent additionally
requires `DECISION_ENABLED`.

| Method and route | Contract |
| --- | --- |
| `POST /v1/research/iterative` | `iterative-research-request-v1`: question, freshness, idempotency key, and optional user-authored candidates/constraints/preferences. Starts one durable run and returns a progress stream. Optional `Last-Event-ID` is validated before creation/claim. Candidate facts/claims are rejected; conservative typed proposals from exact evidence IDs must still pass the Phase 6 verifier. |
| `GET /v1/research/iterative/runs/{run_id}` | Owner-scoped run status, immutable budget snapshot, safe counts, stop reason, gaps, and saved Phase 5 session detail. Read only. |
| `GET /v1/research/iterative/runs/{run_id}/events?after=N` | Persisted safe events after the event sequence. An optional `Last-Event-ID` overrides `after` and must be a persisted sequence. Does not claim a lease or start work. |
| `POST /v1/research/iterative/runs/{run_id}/cancel` | Explicitly makes a nonterminal run cancelled. The cancellation fence prevents later run/session writes. |
| `POST /v1/research/iterative/runs/{run_id}/resume` | Accepts `Last-Event-ID` as the last already-seen sequence (default `-1`), validates it against persisted events before claiming work, then claims an expired lease only when no external side effect is uncertain. An uncertain provider/model attempt is settled conservatively and ends incomplete without redispatch. A live lease returns only persisted events after the cursor. |

Every `research.iterative.*` event is committed with the run transition before
it is streamed. Payloads include only schema/version, run/session IDs, event
sequence, iteration and aggregate query/source/evidence/gap/citation counts,
state, and terminal reason. They exclude question/query text, evidence text,
prompts, provider output/traces, and model reasoning. A client reconnect uses
the read-only events/status routes; it never resumes execution. Resume is a
separate explicit action available only for a safely recoverable expired lease.

The run stores policy and budget versions, idempotency, owner/session links,
current iteration, lease, gaps, assessments, iterations, event sequence,
budget ledger, and terminal reason. Query/source/evidence/citation provenance
stays in the Phase 5 owner-scoped session. Budget use includes iteration,
query, source, token, estimated provider cost, elapsed-time, and unique allowed
domain counts. Configured hostnames are allowlisted before evidence extraction.
Unknown side-effect outcomes are charged at their full reservation and are not
retried. Explicit constraints remain immutable; a Phase 6 decision intent
re-evaluates through the shared entity, claim, constraint, and ranking service.
Any unresolved required gap yields an incomplete/insufficient result with all
open gap classes visible. Firestore storage and index changes are described in
the [Phase 8 guide](phase-8-implementation-guide.md) and [ADRs](decisions/0016-bounded-iterative-research.md).

## Phase 9 identity and account controls

User identity is supplied as a Google `Authorization: Bearer` token or as the
separate `X-User-ID-Token` header forwarded by the web proxy alongside its
Cloud Run identity. Missing/invalid user identity returns a safe 401; disabled
identity mappings return 403. Verification/storage outages fail closed with
503. Responses carry a bounded request ID and no-store security headers.
Exact allowed browser origins are checked; deployment origins must use HTTPS.
Request limits return 429 with `Retry-After`, and emergency switches return 503.
Usage counters estimate requests and do not establish a provider-spend ceiling.

| Route | Contract |
| --- | --- |
| `POST /v1/account/export` | Requires `EXPORT_ENABLED` and a recent Google token; UUID idempotency key; returns bounded owner-only `personal-ai-export-v1` JSON download with an audit event. Limit overflow returns 413. |
| `POST /v1/account/deletion` | Requires `DELETION_ENABLED` and recent Google token; UUID key creates/replays an audited `pending_confirmation` request. |
| `GET /v1/account/deletion/{UUID}` | Requires deletion gate and owner identity; foreign/missing requests return 404. |
| `POST /v1/account/deletion/{UUID}/{confirm\|cancel}` | Recent Google token; audited idempotent state transition; conflicts return 409. Confirmation ends at `confirmed_pending_operator`, with no physical deletion. |

The private worker also exposes `/tasks/maintenance`; it verifies the separate
Scheduler token, requires one active owner mapping, and processes a bounded
expiry/republish batch. It does not physically delete data. Account and
maintenance gates stay off by default.
