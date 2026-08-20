# Phase 1 implementation guide

This guide explains how the Phase 0–1 plan was implemented. The
[implementation plan](phase-1-implementation-plan.md) remains the source of
scope, requirements, and acceptance criteria; this document is the companion
reference for understanding the resulting code and commit history.

## Reading the implementation

The application follows this request path:

```text
Browser chat UI
  -> Next.js /api proxy
  -> FastAPI route
  -> conversation or chat-turn service
  -> owner-scoped repositories
  -> Firestore

For a chat turn, the service also calls:

chat-turn service
  -> provider-neutral LLMClient
  -> Gemini adapter
  -> SSE events back through FastAPI and Next.js
  -> browser state reconciliation
```

Every automated test substitutes in-memory repositories and a fake LLM. Real
Firestore and Gemini access are opt-in manual or deployed checks.

## Current status and remaining verification

The code paths for P0.1 through P1.7 are implemented. The following acceptance
evidence still depends on manual or environment-specific work and is not claimed
as complete:

- The Firestore Emulator create/retrieve check has not been recorded.
- Provider-stream cancellation is implemented, but an automated client-
  disconnect integration test has not been added.
- The credentialed Gemini and deployed GCP smoke tests have not been run in the
  recorded repository session.

These are verification gaps, not hidden automated-test prerequisites. The local
test suites continue to run with no cloud project or model key.

## Commit map

| Plan part | Primary commit | Purpose |
| --- | --- | --- |
| P0.1–P0.2 | `78d8c0b` | Initial decisions, project tooling, CI, and application scaffold |
| P0.3 | `cac6dd4` | Settings, domain/API schemas, and written API contract |
| P1.1 | `6bc5ce5` | Repository protocols, in-memory fakes, Firestore adapters, and indexes |
| P1.2 | `1bb7252` | Provider-neutral LLM boundary and Gemini streaming adapter |
| P0.2 follow-up | `fa45b22` | Correct pnpm ordering in CI |
| P1.3 | `1451402` | Conversation service, dependency injection, and non-streaming routes |
| P1.4 | `29621b0` | Durable chat-turn lifecycle and backend SSE endpoints |
| P1.5 | `35d2b8b` | Frontend shell, typed client, conversation proxy, and basic interactions |
| P1.6 | `b9265ac` | SSE reader, composer, streaming state, regenerate, and edit-and-retry UI |
| P1.7 | `db80333` | Local/deployment documentation, Secret Manager wiring, and verification record |
| Review hardening | `591374a` | Failed-response retry, output bounds, branch reconciliation, OpenAPI, and index provisioning |

The primary commit identifies when a plan part first became usable. Later
cross-cutting fixes are called out in the relevant sections below.

## P0.1 — Phase 1 decisions

Implementation sequence:

1. Record the provider boundary and keep the model identifier in `AI_MODEL`.
2. Select Firestore Native mode while preserving offline repository fakes.
3. Define the temporary `local` owner seam without claiming authentication.
4. Define append-only, branchable history for retry operations.
5. Select SSE as the browser streaming protocol.

Code and documents:

- `docs/decisions/0001-llm-provider-boundary.md`
- `docs/decisions/0002-firestore-native-persistence.md`
- `docs/decisions/0003-single-local-owner.md`
- `docs/decisions/0004-append-only-branchable-message-history.md`
- `docs/decisions/0005-sse-for-assistant-streaming.md`

Verification: each ADR records context, decision, consequences, and accepted
status. Provider data sensitivity is explicitly restricted until the security
boundary is improved.

Commit: `78d8c0b`.

## P0.2 — Quality and test tooling

Implementation sequence:

1. Configure pytest and Ruff in `backend/pyproject.toml`.
2. Configure Vitest, React Testing Library, ESLint, and TypeScript checks.
3. Expose root Make targets for backend/frontend tests, lint, type-check, and
   local servers.
4. Ignore local secrets and generated build/test output while retaining example
   environment files.
5. Run the same offline checks in GitHub Actions without deployment credentials.

Code and documents:

- `backend/pyproject.toml`
- `frontend/package.json`, `frontend/vitest.config.ts`, and
  `frontend/eslint.config.mjs`
- `Makefile` and `.gitignore`
- `.github/workflows/quality.yml`

Verification: `make backend-test`, `make backend-lint`, `make frontend-test`,
`make frontend-lint`, and `make frontend-typecheck` after following the README
environment setup.

Commits: `78d8c0b`; CI pnpm setup corrected by `fa45b22`; `.vite` output ignore
added by `591374a`.

## P0.3 — Settings, schemas, and API contract

Implementation sequence:

1. Load typed environment settings with secret-safe API-key handling.
2. Define UTC-normalized `Conversation` and branchable `Message` records.
3. Define strict request, response, error, and SSE payload schemas.
4. Write the HTTP and event contract before implementing the routes.
5. Verify valid examples, rejected input, environment loading, and generated
   OpenAPI metadata.

Code and documents:

- `backend/src/personal_ai/settings.py`
- `backend/src/personal_ai/entities/conversation.py`
- `backend/src/personal_ai/api/schemas.py`
- `docs/api-contract.md`
- `backend/tests/test_settings.py`, `test_api_schemas.py`, and `test_openapi.py`

Verification: settings load from `backend/.env.example`; schema tests reject
unknown or malformed values; OpenAPI identifies SSE responses as
`text/event-stream` and uses the safe error envelope.

Commits: `cac6dd4`; streaming OpenAPI metadata corrected by `591374a`.

## P1.1 — Conversation and message persistence

Implementation sequence:

1. Define provider-independent conversation and message repository protocols.
2. Implement deterministic, owner-isolated in-memory repositories for tests.
3. Derive the active root-to-leaf path while preserving superseded records.
4. Implement top-level Firestore collections and translate SDK failures into
   application storage errors.
5. Touch conversation timestamps when messages are created or finalized.
6. Define and provision the composite indexes used by list and history queries.

Code and documents:

- `backend/src/personal_ai/storage/repositories.py`
- `backend/src/personal_ai/storage/fake.py`
- `backend/src/personal_ai/storage/firestore.py`
- `backend/src/personal_ai/storage/errors.py`
- `firestore.indexes.json`
- `backend/tests/test_storage_repositories.py`

Verification: repository tests cover ordering, missing resources, owner
isolation, active-path selection, supersession, and conversation timestamp
updates. Automated tests never instantiate Firestore.

Commits: `6bc5ce5`; clean-project index provisioning added to the deploy script
by `591374a`.

## P1.2 — Gemini streaming adapter

Implementation sequence:

1. Define `LLMClient.stream()` around provider-neutral ordered chat messages.
2. Add a deterministic fake that records requests and yields configured deltas.
3. Translate neutral roles into Gemini request objects only inside `llm`.
4. Apply both SDK transport timeout and whole-stream asynchronous timeout.
5. Translate configuration, request, timeout, and availability failures into
   stable application errors.
6. Propagate cancellation so the chat-turn service can persist an incomplete
   result safely.

Code and documents:

- `backend/src/personal_ai/llm/client.py`
- `backend/src/personal_ai/llm/fake.py`
- `backend/src/personal_ai/llm/gemini.py`
- `backend/src/personal_ai/llm/errors.py`
- `backend/tests/test_llm.py` and `test_gemini_manual.py`

Verification: offline tests cover delta ordering and safe error translation.
The credentialed manual test is skipped unless a developer supplies a model
key and explicitly opts in.

Commit: `1bb7252`.

## P1.3 — Conversation service and non-streaming API

Implementation sequence:

1. Add a service that creates, lists, and retrieves owner-scoped conversations.
2. Use a visible default title and return only the active message branch.
3. Compose settings, repositories, `local` ownership, and services through
   FastAPI dependency injection.
4. Implement create/list/get routes under `/v1/conversations`.
5. Translate validation, missing-resource, and storage errors into a consistent
   safe JSON envelope.

Code and documents:

- `backend/src/personal_ai/services/conversations.py`
- `backend/src/personal_ai/api/dependencies.py`
- `backend/src/personal_ai/api/routes.py`
- `backend/src/personal_ai/main.py`
- `backend/tests/test_conversation_routes.py`

Verification: route tests cover empty lists, create/list/get, malformed and
unknown IDs, active-branch filtering, ownership isolation, and storage errors.

Commit: `1451402`.

## P1.4 — Streamed chat-turn lifecycle

Implementation sequence:

1. Validate the conversation and active-history limit before starting a turn.
2. Persist the completed user message and streaming assistant placeholder.
3. Emit `message.created` for each new record.
4. Stream model deltas while retaining only bounded partial content in memory.
5. Persist the final assistant content/status before emitting
   `response.completed`.
6. On provider error or cancellation, persist the partial response as failed
   with a safe code.
7. For regenerate and edit-and-retry, supersede the replaced active path and
   create linked replacement records without deleting history.

Code and documents:

- `backend/src/personal_ai/services/chat_turns.py`
- streaming routes in `backend/src/personal_ai/api/routes.py`
- `backend/tests/test_conversation_routes.py`

Verification: integration tests assert event order, durable completion and
failure, regenerate, edit-and-retry, history-limit rejection, and oversized
provider-response rejection.

Commits: `29621b0`; the aggregate 20,000-character response bound and stable
`llm_invalid_response` failure were added by `591374a`.

## P1.5 — Frontend shell and API boundary

Implementation sequence:

1. Build the responsive sidebar, empty/loading/error states, and main chat area.
2. Define frontend `Conversation`, `Message`, and API error types.
3. Route browser requests through server-side Next.js handlers so the backend
   URL remains server-only.
4. Implement list, create, open, and refresh interactions through one reducer
   state model.
5. Preserve loaded content when recoverable API failures occur.

Code and documents:

- `frontend/src/app/page.tsx` and `page.module.css`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/conversation-proxy.ts`
- `frontend/src/app/api/conversations/**/route.ts`
- `frontend/src/app/page.test.tsx`

Verification: component tests cover the empty state, loaded conversation list,
selection, creation, and recoverable API errors.

Commit: `35d2b8b` (shell and initial client); the shared streaming proxy was
completed in `b9265ac`.

## P1.6 — Composer, streaming UI, and retry controls

Implementation sequence:

1. Add validated keyboard/button submission and block duplicate active sends.
2. Parse SSE frames from a fetch response stream.
3. Add persisted user/assistant records when `message.created` arrives.
4. Append deltas only to the matching streaming assistant and replace it with
   the persisted completion payload.
5. Render partial failed output with a safe error and retry affordance.
6. Implement completed-assistant regenerate and user edit-and-retry actions.
7. When a replacement record arrives, remove its superseded message and all
   displayed descendants immediately so failures cannot leave two active paths.
8. Retry failed assistants through their parent user message, matching the
   backend contract that regenerate targets completed assistants.

Code and documents:

- `frontend/src/lib/api.ts`
- `frontend/src/app/page.tsx`
- streaming proxy routes under `frontend/src/app/api/conversations/`
- `frontend/src/app/page.test.tsx`

Verification: frontend tests cover delta accumulation, completion
reconciliation, visible stream errors, duplicate-submit prevention, regenerate,
edit-and-retry, failed-response retry, and failed replacement-branch cleanup.

Commits: `b9265ac`; failed retry and replacement-branch reconciliation corrected
by `591374a`.

## P1.7 — Local use, deployment, and verification

Implementation sequence:

1. Document prerequisites, installation, environment files, quality commands,
   local servers, and Firestore Emulator use.
2. Create or reuse Firestore, its required composite indexes, service accounts,
   Pub/Sub resources, and Cloud Run services.
3. Grant the API runtime identity access to Firestore and only the configured
   Gemini secret.
4. Inject the key with Cloud Run Secret Manager integration without reading or
   printing it.
5. Keep the worker deployed and idle; chat code does not publish Pub/Sub work.
6. Follow the deployment checklist for health, streamed turn, refresh, and
   Firestore persistence checks.
7. Record local and cloud verification truthfully without credentials or chat
   content.

Code and documents:

- `README.md`
- `infrastructure/gcp/deploy.sh` and `infrastructure/gcp/README.md`
- `docs/gcp-deployment.md`
- `docs/phase-1-deployment-checklist.md`
- `docs/releases/phase-1-vertical-slice.md`

Verification: all local automated checks run without cloud credentials. The
credentialed deployed smoke test remains explicitly unverified until a developer
with GCP access and a Gemini key completes and records the checklist.

Commits: `db80333`; idempotent index creation and its checklist documentation
added by `591374a`.

## Cross-cutting review hardening

Commit `591374a` addressed issues found during the Phase 1 completion review:

- Failed assistant retry now replays the parent user turn through
  edit-and-retry instead of calling completed-only regenerate.
- Replacement SSE events prune the superseded displayed branch immediately,
  including when the replacement later fails.
- Aggregate model output is bounded before persistence or browser delivery.
- OpenAPI advertises streaming responses and safe error envelopes accurately.
- Clean GCP deployments create the Firestore composite indexes required by the
  repository queries.
- Regression tests cover each runtime correction.

## Current verification commands

From an environment prepared according to the root README:

```sh
make backend-test
make backend-lint
make frontend-test
make frontend-lint
make frontend-typecheck
bash -n infrastructure/gcp/deploy.sh
git diff --check
```

For behavior that requires credentials, use the opt-in Gemini manual test and
the Phase 1 deployment checklist rather than placing credentials in test or
source files.
