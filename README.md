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

The scaffold intentionally contains no application features yet.

### Prerequisites

- Python 3.11 or newer, with `pip` and virtual-environment support.
- Node.js 22 and pnpm 11.19.0 (the version pinned by `frontend/package.json`).
- No GCP account, cloud credentials, Firestore Emulator, or Gemini API key is required for the quality checks.

### Install dependencies

Create and activate an isolated Python environment, then install the backend development dependencies:

```sh
python -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "./backend[dev]"
```

Install the frontend dependencies from the committed lockfile:

```sh
cd frontend
pnpm install --frozen-lockfile
```

### Configure local environment files

Copy `backend/.env.example` to `backend/.env` when configuring the API, and copy `frontend/.env.local.example` to `frontend/.env.local` when configuring the UI. Leave provider credentials empty unless an implementation task specifically requires them.

Only example environment files are committed. Local `.env` and `.env.*` files are ignored; never place credentials or personal data in a tracked file.

### Local quality commands

Run these commands from the repository root. They do not need cloud credentials or a model key.

| Command | Check |
| --- | --- |
| `make backend-test` | Backend pytest suite |
| `make backend-lint` | Backend Ruff checks |
| `make frontend-test` | Frontend Vitest suite |
| `make frontend-lint` | Frontend ESLint checks |
| `make frontend-typecheck` | Frontend TypeScript checks |

For local development, run `make run-backend` and `make run-frontend` in separate terminals. The API listens on port 8000 and the web app on port 3000.

To verify that a check detects a failure, temporarily change either health-test assertion or the frontend expected application name, run its corresponding command, and then revert that temporary edit. CI runs the same five quality checks on pull requests and pushes to `main`; it does not deploy or use secrets.

Start with the [project brief](docs/project-brief.md) in a new session. It captures the project intent, current state, guardrails, and immediate implementation target. See [architecture notes](docs/architecture.md) for component boundaries and [research-agent notes](docs/research-agent.md) for the future search-agent model.

## Principles

- Keep the model provider behind the `llm` module.
- Keep durable user memory separate from time-sensitive external evidence.
- Let memory guide research and ranking, never silently replace current evidence.
- Keep search providers and domain-specific APIs behind adapters.
- Treat experiments as disposable until measured results justify promotion.
- Avoid putting credentials or user data in version control.
