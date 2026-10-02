# Personal AI System

A personal AI system and research playground: chat, long-term memory, and evidence-grounded search agents. It is designed as one reusable research platform, with travel and shopping as the first domain modules rather than separate applications.

## Initial technology stack

- **Web:** Next.js, React, and TypeScript, deployed as a Cloud Run service.
- **API and worker:** Python, FastAPI, and Uvicorn, deployed as separate Cloud Run services.
- **Durable application data:** Cloud Firestore in Native mode.
- **Asynchronous work:** Pub/Sub push delivery to the worker for research, consolidation, and expiry-maintenance jobs.
- **Secrets:** Secret Manager; no provider key is committed to source control.
- **Build and delivery:** Dockerfiles plus `gcloud run deploy --source`.

The GCP layout and deployment path are documented in [GCP deployment](docs/gcp-deployment.md).

## Repository layout

```text
frontend/                    Next.js interface for chat and research
backend/                     FastAPI application and domain packages
  src/personal_ai/
    agents/                  Conversation and research orchestration
    memory/                  Preference, episodic, and semantic memory
    search/                  Search pipeline and provider adapters
    evidence/                Fresh, attributable source observations
    entities/                Canonical entities and entity resolution
    ranking/                 Constraints and domain-specific scoring
    domains/                 Travel and shopping domain adapters
    evaluation/              Reproducible system and agent evaluation
infrastructure/              Local and cloud deployment configuration
experiments/                 Isolated memory, search, and ranking experiments
docs/                        Architecture, data-model, and decision notes
```

## Getting started

Phase 1 is a single-user chat vertical slice: create and reopen conversations,
stream Gemini responses, and persist the active message history in Firestore.
The temporary owner is always `local`; there is no authentication. Do not use
the public bootstrap deployment for sensitive personal data.

### Prerequisites

- Python 3.11 or newer (the Docker image uses Python 3.12) and uv 0.11.13.
- Node.js 22 and pnpm 11.19.0 (the version pinned by `frontend/package.json`).
- No GCP account, cloud credentials, Firestore Emulator, or Gemini API key is required for the quality checks.

### Install dependencies

Install the backend from its committed lockfile, including locked build tools,
then activate the isolated environment:

```sh
cd backend
uv sync --locked --only-group build --no-install-project
uv sync --locked --extra dev --group build --no-build-isolation
cd ..
source backend/.venv/bin/activate
```

Install the frontend dependencies from the committed lockfile:

```sh
cd frontend
pnpm install --frozen-lockfile
```

### Configure local environment files

Copy `backend/.env.example` to `backend/.env` when configuring the API, and copy `frontend/.env.local.example` to `frontend/.env.local` when configuring the UI. Leave provider credentials empty unless an implementation task specifically requires them.

Only example environment files are committed. Local `.env` and `.env.*` files are ignored; never place credentials or personal data in a tracked file.

For a local UI-only or route check, the default `AI_API_KEY=` is enough until a
chat turn is sent. For a real streamed response, set `AI_API_KEY` to a Gemini
key and choose an available `AI_MODEL`; a missing key produces the safe
`invalid_configuration` stream error. Never use a production key in a tracked
file. Automated tests use fake repositories and a fake LLM, so they need
neither a key nor GCP credentials.

### Local Firestore persistence

For manual persistence testing, install the Google Cloud CLI plus the Firestore
emulator component, then run the emulator in a separate terminal:

```sh
gcloud components install cloud-firestore-emulator
gcloud emulators firestore start --host-port=127.0.0.1:8080
```

Keep `FIRESTORE_PROJECT_ID=example-personal-ai` and
`FIRESTORE_EMULATOR_HOST=127.0.0.1:8080` in `backend/.env` (the example file
already contains equivalent values). This is opt-in: tests never contact the
emulator or Firestore. If the emulator is not running, use the fake-backed test
suite rather than starting the API with Firestore configured.

### Local quality commands

Run these commands from the repository root. They do not need cloud credentials or a model key.

| Command | Check |
| --- | --- |
| `make backend-test` | Backend pytest suite |
| `make backend-lint` | Backend Ruff checks |
| `make frontend-test` | Frontend Vitest suite |
| `make frontend-lint` | Frontend ESLint checks |
| `make frontend-typecheck` | Frontend TypeScript checks |
| `make context-eval` | Synthetic Phase 2 context evaluation |
| `make memory-eval` | Synthetic Phase 3 memory evaluation |
| `make backend-build` | Backend source distribution and wheel |
| `make frontend-build` | Next.js production build |

For local development, run `make run-backend` and `make run-frontend` in separate terminals. The API listens on port 8000 and the web app on port 3000.

Open `http://localhost:3000`, create a conversation, and send a message after
both the emulator and a valid model key are configured. Refresh the page to
confirm that the completed conversation was persisted. If the page shows API
unavailable, confirm the backend is running and `API_BASE_URL` remains
`http://localhost:8000`; if the turn fails with invalid configuration, set the
model key and verify `AI_PROVIDER=gemini` and `AI_MODEL` in `backend/.env`.

To verify that a check detects a failure, temporarily change either health-test assertion or the frontend expected application name, run its corresponding command, and then revert that temporary edit. CI runs the five quality checks, backend packaging on Python 3.11/3.12, the Next.js production build, and both Docker builds on pull requests and pushes to `main`; it does not deploy or use secrets.

See [dependency and build management](docs/dependency-management.md) for lockfile
updates, Docker build commands, and the limits of build reproducibility.

For AI coding sessions, follow [AGENTS.md](AGENTS.md), then start with the
[project brief](docs/project-brief.md). It
captures the project intent, current state, guardrails, and immediate
implementation target. The
[Phase 1 implementation plan](docs/phase-1-implementation-plan.md) defines the
work and acceptance criteria; its companion
[implementation guide](docs/phase-1-implementation-guide.md) maps every part to
the delivered code, tests, and commits. See
[architecture notes](docs/architecture.md) for component boundaries and
[research-agent notes](docs/research-agent.md) for the future search-agent
model.

Phase 1 code and local disconnect regression tests are implemented; real
persistence/provider/deployment and deployed browser cancellation verification
remain open. The
[verification closeout plan](docs/phase-1-verification-plan.md) outlines that
work. Phase 2 context-window management is implemented locally; see the
[implementation guide](docs/phase-2-implementation-guide.md) and
[verification record](docs/releases/phase-2-context-management.md).

## Context-window management

Every model turn uses a token budget, a compatible working summary when useful,
and complete recent active-branch turns. The newest prompt is never dropped or
truncated. An oversized prompt remains persisted without an assistant and can
be shortened with **Edit and retry**. Summaries are lossy conversation context,
not long-term memory, and do not promise perfect recall.

Backend example settings include a 32,768-token application capacity, 4,096-token
response reserve, 1,024-token safety margin, 12,000-token summary trigger, and
2,048-token summary ceiling. Validate these against `AI_MODEL` when changing it.
`MAX_PHASE_1_HISTORY_MESSAGES` has been replaced by the token budget.
Production counting uses Gemini; offline planning/inspection clearly labels estimates.

Run `make context-eval` for the five synthetic offline regression fixtures.
For the read-only development view, enable `CONTEXT_INSPECTION_ENABLED=true`
in both local environment files, restart the servers, and open
`http://localhost:3000/development/context`. Both applications default to false;
the deployment script keeps the view disabled. Provider quality verification is
opt-in as described in the implementation guide.

## Deploy and verify Phase 1

Follow the [GCP deployment guide](docs/gcp-deployment.md) and complete the
[Phase 1 deployment checklist](docs/phase-1-deployment-checklist.md). The
deployer reads the model key only from Secret Manager. The current bootstrap
leaves both web and API services public and has no authentication; it is not
appropriate for sensitive personal data.

## Principles

- Keep the model provider behind the `llm` module.
- Keep durable user memory separate from time-sensitive external evidence.
- Let memory guide research and ranking, never silently replace current evidence.
- Keep search providers and domain-specific APIs behind adapters.
- Treat experiments as disposable until measured results justify promotion.
- Avoid putting credentials or user data in version control.

## Simple long-term memory

Phase 3 is implemented locally and disabled by default. When deliberately enabled,
the system extracts a few exact, attributable user statements from successfully
completed turns, stores their provenance and compatible embeddings, and retrieves
relevant historical context across conversations. Selected records pass through
the same total token budget as working summaries and recent turns. Memory is
fallible user knowledge, not external evidence or guaranteed recall. Current
requests and corrections take precedence. There is no automatic contradiction
resolution, editing, consolidation or forgetting.

Review provider-data suitability before setting `MEMORY_ENABLED=true` and
`MEMORY_EXTRACTION_ENABLED=true`; the current `local` owner and public bootstrap
are not authentication. Provision the matching Firestore vector index before
enabling retrieval. Run `make memory-eval` for fourteen offline synthetic cases.
The development context inspector can estimate fit for explicitly supplied memory
IDs when `MEMORY_INSPECTION_ENABLED=true` is set in both local environment files;
it makes no provider calls and does not replay prior model requests.
See the [Phase 3 guide](docs/phase-3-implementation-guide.md),
[decisions](docs/decisions/0009-simple-attributable-memory.md), and
[release evidence](docs/releases/phase-3-simple-memory.md) for configuration,
index ordering, manual checks and remaining gaps. Phase 4 has not started.
