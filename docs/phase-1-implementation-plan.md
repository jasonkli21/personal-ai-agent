# Phase 0–1 implementation plan

This is the execution plan for the first usable vertical slice: a single-user chat application with persisted conversations and streamed model responses. It is intentionally narrower than the long-term architecture.

Read [project brief](project-brief.md) first. Its constraints override convenience decisions in this plan.

## Scope boundary

Phase 1 includes only conversation chat:

- One logical personal user, with no authentication yet.
- Conversation and message persistence in Firestore.
- A Gemini-backed, replaceable LLM adapter.
- Server-sent event (SSE) streaming.
- Create/list/open conversation; send, regenerate, and edit-and-retry a message.
- A minimal responsive web UI and local/deployed verification.

Phase 1 explicitly excludes long-term memory, embeddings, search, agents, evidence, entity resolution, ranking, Pub/Sub publishing, and domain modules. Context is limited to a small active conversation history; token budgeting, summarization, and context inspection start in Phase 2.

## Dependency map

```text
P0.1 Decisions ──> P0.3 Settings/contracts ──> P1.1 Persistence ──> P1.3 API
       |                    |                         |                  |
       |                    └──> P1.2 LLM adapter ────┴──> P1.4 Streaming  |
P0.2 Tooling ────────────────────────────────────────────────────────────────┤
                                                                             v
P1.5 Web shell ───────────────────────────────────────────────────────> P1.6 Chat UI
P1.4 Streaming ───────────────────────────────────────────────────────> P1.6 Chat UI
P1.6 Chat UI + P1.4 Streaming ────────────────────────────────────────> P1.7 E2E/deploy
```

Tasks marked **decision required** should stop for user input only when the documented default is unsuitable. All other tasks should be implementable without expanding the phase.

---

## Phase 0 — Foundation

### P0.1 — Record the Phase 1 decisions

**Dependencies:** none  
**Decision required:** yes

**Goal:** eliminate the few choices that would otherwise cause incompatible implementation work.

**Work:** create `docs/decisions/` and add short architecture-decision records covering:

1. **LLM:** Google Gen AI Python SDK with a Gemini chat model selected at implementation time; model ID comes from `AI_MODEL`. The rest of the app depends only on the internal `LLMClient` protocol.
2. **Persistence:** Firestore Native mode in deployed environments. Local tests use a fake repository; local manual development may use the Firestore Emulator when configured.
3. **Identity:** the initial application is single-user and assigns persisted records `owner_id = "local"`. It does not claim to be authenticated. Every repository method accepts `owner_id` so Phase 9 can replace it with a real identity without redesigning storage.
4. **Message history:** Phase 1 stores an append-only branchable message history. The active branch is selected by the latest non-superseded path; older messages remain auditable.
5. **Streaming:** browser-facing assistant output uses SSE, not WebSockets.

**Requirements:**

- Each record includes context, decision, consequences, and status (`accepted`).
- Do not lock a Gemini model ID into source code; keep it in environment configuration.
- Document whether the chosen provider and account are acceptable for the intended data sensitivity before real personal data is used.

**Acceptance criteria:**

- Five ADRs exist and agree with this plan and the project brief.
- No product code has been added.
- A subsequent task can use the decisions without making a competing storage, identity, or streaming choice.

**Out of scope:** selecting search providers, embeddings, memory models, or a permanent authentication provider.

### P0.2 — Establish local quality and test tooling

**Dependencies:** none

**Goal:** make every later task independently verifiable.

**Work:**

- Add backend test configuration for `pytest` and `ruff` in `pyproject.toml`.
- Add a frontend test approach appropriate for the initial UI (for example, Vitest plus React Testing Library) and the necessary scripts.
- Add root-level developer commands or a `Makefile`/task runner for backend test, backend lint, frontend test, frontend lint/type-check, and local run.
- Add `.env` handling rules: example files are committed; real files are ignored.
- Add a GitHub Actions workflow that runs the backend and frontend checks without deploying.

**Requirements:**

- Test commands must run without real cloud credentials and without a real LLM key.
- Backend tests must use dependency injection/fakes instead of network calls.
- The CI workflow must not expose secrets or require a GCP project.

**Acceptance criteria:**

- One documented command runs each backend check and each frontend check.
- CI runs on a clean checkout and performs no deployment.
- A deliberately failing backend test and frontend test are detected by their respective commands.

**Out of scope:** end-to-end browser automation, coverage targets, or production observability.

### P0.3 — Define application settings, schemas, and API contract

**Dependencies:** P0.1

**Goal:** establish stable boundaries before persistence, provider, API, and UI implementations begin.

**Work:**

- Add typed backend settings, loaded from environment, including `AI_PROVIDER`, `AI_MODEL`, `AI_API_KEY`, `FIRESTORE_PROJECT_ID`, `FIRESTORE_EMULATOR_HOST`, `REQUEST_TIMEOUT_SECONDS`, `MAX_PHASE_1_HISTORY_MESSAGES`, and allowed web origin(s).
- Define Pydantic request/response schemas and domain records for `Conversation` and `Message`.
- Add API documentation describing the routes and SSE event format below.

**Required data fields:**

| Record | Required fields |
| --- | --- |
| Conversation | `id`, `owner_id`, `title`, `created_at`, `updated_at` |
| Message | `id`, `conversation_id`, `owner_id`, `role` (`user` or `assistant`), `content`, `status` (`streaming`, `completed`, `failed`, `superseded`), `created_at`, `parent_message_id` (nullable), `supersedes_message_id` (nullable), `model` (nullable), `error_code` (nullable) |

**Required HTTP contract:**

| Method | Route | Behavior |
| --- | --- | --- |
| `GET` | `/health` | Existing service readiness response |
| `POST` | `/v1/conversations` | Create and return a conversation |
| `GET` | `/v1/conversations` | Return current owner’s conversations, newest first |
| `GET` | `/v1/conversations/{id}` | Return conversation plus active-branch messages |
| `POST` | `/v1/conversations/{id}/messages` | Persist user message, stream an assistant response |
| `POST` | `/v1/conversations/{id}/messages/{id}/regenerate` | Stream a replacement for a completed assistant message |
| `POST` | `/v1/conversations/{id}/messages/{id}/edit-and-retry` | Create a replacement user message with supplied content, then stream its response |

**Required SSE events:**

| Event | Required payload |
| --- | --- |
| `message.created` | persisted user or assistant message metadata |
| `response.delta` | `message_id`, incremental `delta` text |
| `response.completed` | final persisted assistant message |
| `response.error` | `message_id`, stable error `code`, safe user-facing `message` |

**Requirements:**

- All timestamps are UTC ISO 8601 values.
- Route IDs are UUIDs; malformed IDs and unknown resources return consistent 4xx responses.
- Never return provider keys, internal exception traces, or unbounded provider output.
- Title creation may be deterministic from the first user message; no title-generation model call is allowed in Phase 1.

**Acceptance criteria:**

- Settings load successfully from `.env.example` with fake values.
- Schema and OpenAPI tests cover valid and invalid request examples.
- The route and SSE specifications are documented before route implementation begins.

**Out of scope:** memory/evidence schemas, token counting, pagination beyond a reasonable fixed Phase 1 limit, and authenticated ownership.

---

## Phase 1 — Basic chat

### P1.1 — Implement Firestore conversation and message repositories

**Dependencies:** P0.2, P0.3

**Goal:** create a storage boundary that supports basic chat and later identity migration without leaking Firestore details into API code.

**Work:**

- Define repository protocols in `storage` for conversation and message operations.
- Implement Firestore repositories using separate top-level collections such as `conversations` and `messages`; messages must be queried by `conversation_id` and active branch.
- Implement an in-memory fake repository for tests.
- Add Firestore index definitions or setup documentation for the required composite queries.
- Implement create/list/get/update operations needed by the Phase 1 API contract.

**Requirements:**

- Every storage operation scopes by `owner_id`.
- Conversation list is ordered by `updated_at` descending.
- Messages are returned in chronological order for the selected active path.
- A new regenerate or edit-and-retry operation marks only the replaced message/path as `superseded`; it never deletes old content.
- `updated_at` changes whenever a message is added or finalized.
- The repository maps Firestore failures to typed application errors; API code does not import Firestore SDK classes.

**Acceptance criteria:**

- Repository tests use the fake implementation and cover create, list, retrieval, missing resource, ownership isolation, ordering, and supersession.
- A manual emulator test can create and retrieve a conversation without changes to application code.
- No Firestore call occurs during unit tests unless explicitly running an emulator integration suite.

**Out of scope:** migrations for live user data, vector storage, full-text search, TTL deletion, and real authentication.

### P1.2 — Implement the replaceable Gemini streaming adapter

**Dependencies:** P0.1, P0.2, P0.3

**Goal:** make one model provider work through a small internal interface that can be faked and replaced.

**Work:**

- Define an `LLMClient` protocol with a method that accepts ordered chat messages and asynchronously yields text deltas.
- Implement a Gemini adapter using settings, explicit request timeout, and provider-supported streaming.
- Add a deterministic fake LLM client for tests.
- Translate provider failures into stable application errors: unavailable, timeout, invalid configuration, and invalid request.
- Keep provider request/response objects inside `llm`.

**Requirements:**

- `AI_API_KEY` is read only from local environment in development or Secret Manager-injected environment variables in Cloud Run; it is never logged.
- The adapter receives only the active conversation history, capped by `MAX_PHASE_1_HISTORY_MESSAGES`.
- The system prompt, if any, is a short Phase 1 chat-only instruction. It must not claim memory, web access, tool use, or citation support.
- Cancellation/disconnect must stop consuming the provider stream and allow the API to mark the assistant message as failed or incomplete safely.

**Acceptance criteria:**

- Unit tests prove delta ordering with the fake client.
- Unit tests prove timeout/configuration/provider failures map to safe error codes.
- A credentialed opt-in manual test can stream from the configured Gemini model without changing source code.

**Out of scope:** embeddings, function calling, tool use, structured outputs, model fallback, and long-context handling.

### P1.3 — Implement conversation service and non-streaming routes

**Dependencies:** P0.2, P0.3, P1.1

**Goal:** expose reliable create, list, and retrieve operations before introducing streamed turns.

**Work:**

- Add an application service that coordinates repositories and applies Phase 1 ownership/branching rules.
- Implement `POST /v1/conversations`, `GET /v1/conversations`, and `GET /v1/conversations/{id}`.
- Add dependency injection for settings, repositories, and the current Phase 1 owner (`local`).
- Add consistent JSON error responses for validation errors, unknown conversations, and storage failures.

**Requirements:**

- A new conversation has a user-visible default title and no messages.
- The response for a retrieved conversation includes only the active message path, never raw Firestore internals.
- List and get routes must not call the LLM.
- API versioning stays under `/v1` except the existing health route.

**Acceptance criteria:**

- Route tests cover success, unknown ID, malformed ID, and empty conversation list.
- OpenAPI output matches the documented schemas.
- Tests prove no data is returned for a different owner through the repository interface.

**Out of scope:** pagination UI, deleting conversations, searching history, user accounts, and message mutation routes.

### P1.4 — Implement streamed message, regenerate, and edit-and-retry flows

**Dependencies:** P0.2, P0.3, P1.1, P1.2, P1.3

**Goal:** complete the backend chat turn lifecycle with durable message states and SSE.

**Work:**

- Implement `POST /v1/conversations/{id}/messages` as an SSE response.
- Persist the user message before contacting the LLM.
- Create a `streaming` assistant message before emitting deltas; append deltas in memory during the request and persist the final content/status on completion.
- Implement regenerate for a completed assistant message: retain the original, create a replacement assistant message, and mark the replaced response superseded.
- Implement edit-and-retry for a user message: retain the original, create a replacement user message with supplied content, mark the old user message and descendant active responses superseded, then generate a replacement assistant message.
- Handle client disconnect, provider error, and timeout by persisting a `failed` assistant message with a safe `error_code`.

**Requirements:**

- SSE headers disable buffering and caching as appropriate for streaming.
- Event order for a successful turn is `message.created` (user), `message.created` (assistant), zero or more `response.delta`, then `response.completed`.
- The completed event contains the persisted final assistant content, not merely a reconstructed browser value.
- A failed stream emits exactly one `response.error` and leaves the conversation usable for retry.
- The backend must enforce a Phase 1 history cap; if exceeded, return a clear error instructing the user to start a new chat. Do not silently truncate yet.
- Logs contain request IDs and error class, but never prompt text, response text, or secrets by default.

**Acceptance criteria:**

- Integration tests with fake repository and fake LLM assert the full event sequence and final persistence state.
- Tests cover model timeout, model error, client cancellation, regenerate, edit-and-retry, and history-cap rejection.
- A manual local test displays streamed text and persists the final response after page reload.

**Out of scope:** automatic title generation, response voting, attachment support, parallel branches UI, context summaries, and background tasks.

### P1.5 — Build the frontend application shell and API client

**Dependencies:** P0.2, P0.3, P1.3

**Goal:** establish a small, typed frontend boundary before rendering streaming chat behavior.

**Work:**

- Add a layout with conversation sidebar, main chat area, loading/empty/error states, and basic mobile behavior.
- Implement a typed API client plus server-side Next.js proxy routes where necessary so `API_BASE_URL` is not exposed to the browser.
- Implement create, list, and open conversation UI interactions.
- Use a single explicit client-side state model for selected conversation, messages, request state, and errors.

**Requirements:**

- The UI must call only the documented `/v1` routes and health proxy; no direct Firestore or provider calls.
- Empty state offers “New conversation.”
- API/network failures are visible and recoverable without losing an already loaded conversation.
- Accessibility baseline: keyboard-accessible controls, labelled text input/buttons, sensible focus after creating or opening a conversation, and no color-only error state.

**Acceptance criteria:**

- Component tests cover empty state, loaded conversation list, selecting a conversation, and API error state.
- A manual local run can create a conversation and reopen it after refresh.
- No streaming UI has been added yet; that belongs to P1.6.

**Out of scope:** rich Markdown/code rendering, message edit controls, theming, user preferences, and responsive visual polish beyond basic usability.

### P1.6 — Add the chat composer, SSE rendering, and retry controls

**Dependencies:** P0.2, P1.4, P1.5

**Goal:** deliver the complete Phase 1 user interaction using the established backend contract.

**Work:**

- Add a composer with submission validation, disabled/pending state, and keyboard submit behavior.
- Consume SSE with a fetch-based stream reader; update only the in-progress assistant message as deltas arrive.
- Reconcile the final UI message with the `response.completed` payload.
- Add regenerate on completed assistant messages and edit-and-retry on user messages.
- Render failed messages with a retry affordance and a safe error description.
- Render plain text first; optionally render safe Markdown only if it can be implemented and tested within the task without new dependencies that obscure the learning goal.

**Requirements:**

- Prevent duplicate sends while a conversation has an active request.
- Preserve partial streamed text if an error occurs, but clearly mark it failed rather than presenting it as a completed answer.
- After regenerate/edit-and-retry, replace the displayed active path with the new path; Phase 1 need not expose a branch browser.
- Do not put model keys, Firestore credentials, or provider URLs in browser-accessible variables.

**Acceptance criteria:**

- Frontend tests cover delta accumulation, completed response replacement, error rendering, disabled duplicate submit, regenerate, and edit-and-retry UI actions.
- Manual local test demonstrates each interaction and retains the final conversation after reload.
- Browser console contains no secrets and no unhandled stream errors.

**Out of scope:** attachments, voice, Markdown extensions, citations, tool-progress visualization, and multi-user synchronization.

### P1.7 — Document, deploy, and verify the Phase 1 vertical slice

**Dependencies:** P0.2, P1.4, P1.6

**Goal:** make the completed chat application reproducible locally and deployable to the existing GCP topology.

**Work:**

- Update the root README with exact local prerequisites, environment setup, backend/frontend run commands, tests, and troubleshooting for missing model credentials.
- Add an opt-in local Firestore Emulator setup or a clearly documented fake-development mode; do not make tests require cloud credentials.
- Update `infrastructure/gcp/deploy.sh` to inject the configured model key from Secret Manager into the API service without printing it.
- Keep the worker deployed but idle; Phase 1 must not publish Pub/Sub messages.
- Add a deployment checklist: billing budget, alert, secret creation, deploy, health verification, one chat turn, persistence verification, and teardown/cleanup guidance.
- Run the complete local test suite and a credentialed deployed smoke test when the user supplies GCP access and a provider key.

**Requirements:**

- The deployed API’s model key is sourced from Secret Manager, not a committed file or shell history.
- API and web endpoints remain public only as documented by the current bootstrap; the documentation must repeat that this is unsuitable for sensitive personal data until authentication is implemented.
- The GCP smoke test verifies: web loads, web reaches API, a conversation is created, a streamed turn completes, and the conversation persists in Firestore.
- The deploy script is idempotent for existing Firestore, Pub/Sub, service account, and Cloud Run resources.

**Acceptance criteria:**

- A developer starting from a clean checkout can run tests locally without cloud credentials.
- A developer with the documented GCP prerequisites can deploy without editing application source.
- The deployment checklist has been executed once and its results recorded in a non-secret release note or issue.
- No Phase 2+ behavior has been added to make deployment work.

**Out of scope:** production authentication, custom domain, CI/CD deployment, private ingress, scheduled jobs, telemetry dashboards, backups, and data deletion workflows.

## Phase 1 completion review

Before declaring Phase 1 done, verify all task acceptance criteria and answer these questions:

1. Can a user create, reopen, and continue a short conversation after a restart?
2. Is every final or failed assistant response represented by a persisted message state?
3. Can user-facing streaming errors be retried without corrupting history?
4. Is provider-specific code isolated to `llm`?
5. Can all automated tests run with no GCP project or model key?
6. Does the application make no claim of memory, search, or current-information capability?

Only after all answers are yes should work advance to Phase 2.
