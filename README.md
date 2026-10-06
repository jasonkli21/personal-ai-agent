# Personal AI System

A personal AI platform and research environment focused on the systems around large language models: streaming chat, context management, long-term memory, evidence-grounded research, decision support, domain integrations, evaluation, and application-facing AI capabilities.

The project is intentionally not a model-training or local-model-hosting project. It uses hosted model/provider APIs behind replaceable interfaces and concentrates on the surrounding architecture: memory, retrieval, evidence, routing, constraints, persistence, observability, and cost-aware orchestration.

## What it does

The system provides reusable AI capabilities that can be used directly through its web UI or consumed by domain applications such as travel and shopping.

Core capabilities include:

- streamed conversational chat;
- persistent conversation history;
- token-budgeted context management and working summaries;
- attributable long-term memory with retrieval;
- bounded memory lifecycle experiments;
- source-grounded research with persisted evidence;
- iterative research with explicit budgets and recovery;
- canonical research entities and evidence-backed claims;
- deterministic hard constraints and explainable ranking;
- decision snapshots with source attribution;
- travel and shopping comparison modules;
- itinerary-proposal and booking-extraction capability boundaries;
- owner-scoped application/workspace identity foundations;
- account export/deletion workflow foundations;
- synthetic evaluation suites for memory, context, research, decisions, and domain behavior.

## Design principles

- **The model provider is replaceable.**
- **Memory and external evidence are different data classes.**
- **Current evidence can override stale memory.**
- **Hard constraints are enforced by application code, not delegated to a model.**
- **Research is bounded by time, token, source, and cost budgets.**
- **Domain applications keep authority over their own data and business rules.**
- **Experiments require measurable evaluation before promotion.**
- **Cloud resources should scale to zero or stay disabled when not needed.**

## Architecture

```text
                         Browser
                            |
                            v
                +-----------------------+
                | Next.js / React       |
                | public web service    |
                +-----------+-----------+
                            |
                     server-side proxy
                            |
                            v
                +-----------------------+
                | private FastAPI API   |
                |                       |
                | chat + context        |
                | memory + research     |
                | evidence + decisions  |
                | domain capabilities   |
                +----+-------------+----+
                     |             |
                     |             +-------> hosted LLM/search providers
                     |
                     v
               Firestore Native
                     |
                     | durable async jobs
                     v
                   Pub/Sub
                     |
                     v
              private Cloud Run
                   worker
```

Domain applications integrate over explicit HTTP contracts rather than importing internal packages.

## Repository layout

```text
.
├── backend/
│   ├── src/personal_ai/
│   │   ├── agents/          # research orchestration
│   │   ├── auth/            # identity and owner boundaries
│   │   ├── context/         # token-budgeted context assembly
│   │   ├── decisions/       # evidence-backed decision contracts
│   │   ├── domains/         # thin travel/shopping capabilities
│   │   ├── entities/        # chat and canonical research entities
│   │   ├── evidence/        # attributable observations
│   │   ├── evaluation/      # reproducible synthetic evaluation
│   │   ├── memory/          # durable memory and lifecycle logic
│   │   ├── ranking/         # deterministic ranking/constraints
│   │   ├── search/          # search adapters and pipeline
│   │   ├── services/        # chat/application orchestration
│   │   └── storage/         # Firestore and persistence primitives
│   └── tests/
├── frontend/
│   ├── src/                 # Next.js application and API proxies
│   └── tests/
├── infrastructure/          # local/GCP deployment assets
├── experiments/             # isolated research experiments
├── docs/                    # architecture, ADRs, runbooks, evaluations
├── firestore.indexes.json
└── Makefile
```

## Tech stack

### Web

- Next.js 15
- React 19
- TypeScript
- pnpm 11.19.0

### API / worker

- Python 3.11+
- FastAPI
- Uvicorn
- Google Gen AI SDK behind an application-level provider abstraction

### Cloud

- Google Cloud Run
- Cloud Firestore Native mode
- Pub/Sub
- Secret Manager
- Artifact Registry
- Cloud Build

## Local setup

### Prerequisites

- Python 3.11+; Python 3.12 is used by the containerized runtime
- `uv` 0.11.13
- Node.js 22
- pnpm 11.19.0
- optional Google Cloud CLI for the Firestore emulator

### 1. Clone the repository

```bash
git clone https://github.com/jasonkli21/personal-ai-system.git
cd personal-ai-system
```

### 2. Install backend dependencies

```bash
cd backend

uv sync --locked --only-group build --no-install-project
uv sync --locked --extra dev --group build --no-build-isolation

cd ..
source backend/.venv/bin/activate
```

### 3. Install frontend dependencies

```bash
cd frontend
pnpm install --frozen-lockfile
cd ..
```

### 4. Configure local environment files

```bash
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local
```

The default local configuration keeps optional research, memory-lifecycle, decision, domain, export, deletion, and provider-backed features disabled.

Automated tests use fakes and do not require model credentials or GCP access.

### 5. Optional: start the Firestore emulator

For manual persistence testing:

```bash
gcloud components install cloud-firestore-emulator
gcloud emulators firestore start --host-port=127.0.0.1:8080
```

The example backend environment already points to:

```env
FIRESTORE_PROJECT_ID=example-personal-ai
FIRESTORE_EMULATOR_HOST=localhost:8080
```

### 6. Start the application

In separate terminals:

```bash
make run-backend
```

```bash
make run-frontend
```

Open:

```text
http://localhost:3000
```

The frontend server-side proxy defaults to:

```env
API_BASE_URL=http://localhost:8000
```

## Model and provider configuration

The default model configuration is Gemini:

```env
AI_PROVIDER=gemini
AI_MODEL=gemini-2.5-flash
AI_API_KEY=
```

Leave `AI_API_KEY` empty for offline/fake-backed testing.

For a real streamed model response, set the key only in the untracked local environment file or Secret Manager in cloud deployments.

Research, memory, decision, travel, shopping, proposal, and extraction capabilities each have independent gates. Enable only the specific path you are testing and preserve its provider/storage policy controls.

## Quality and evaluation

Common checks from the repository root:

```bash
make backend-test
make backend-lint
make frontend-test
make frontend-lint
make frontend-typecheck
make backend-build
make frontend-build
```

The repository also includes deterministic evaluation suites:

```bash
make context-eval
make memory-eval
make memory-lifecycle-eval
make research-eval
make iterative-research-eval
make decision-eval
make domain-eval
```

These evaluations are designed to make changes to memory, retrieval, ranking, context assembly, and research behavior measurable rather than purely subjective.

## Cloud deployment

The deployed topology is designed around a public web shell, private API/worker services, Firestore, and authenticated Pub/Sub delivery.

```text
Browser
  |
  v
Cloud Run: personal-ai-web
  |
  | service identity + end-user identity
  v
Cloud Run: personal-ai-api
  |
  +------> Firestore
  |
  +------> hosted model/search providers
  |
  +------> Pub/Sub ---> Cloud Run: personal-ai-worker
```

### Prerequisites

Provision or prepare:

1. a GCP project with billing enabled;
2. a Google OAuth web client;
3. a Gemini API key stored in Secret Manager;
4. a reviewed staging domain/origin;
5. appropriate Cloud Run, Firestore, Pub/Sub, Secret Manager, IAM, and Artifact Registry permissions.

### Store the model key

Example:

```bash
printf '%s' "$GEMINI_API_KEY" | \
  gcloud secrets create personal-ai-gemini-api-key \
  --replication-policy=automatic \
  --data-file=-
```

Do not place the key in repository files or command-line arguments.

### Deploy

From a clean reviewed commit:

```bash
chmod +x infrastructure/gcp/deploy.sh

infrastructure/gcp/deploy.sh \
  staging \
  YOUR_STAGING_PROJECT \
  us-central1 \
  personal-ai-gemini-api-key \
  gemini-2.5-flash \
  YOUR_GOOGLE_OAUTH_WEB_CLIENT_ID.apps.googleusercontent.com \
  owner@example.com \
  https://personal.example \
  2
```

The deployment script:

- enables required GCP APIs;
- creates Firestore and indexes;
- builds backend/frontend images;
- resolves immutable image digests;
- deploys separate web, API, and worker services;
- creates scoped service identities;
- configures authenticated Pub/Sub delivery;
- injects the model key from an explicit Secret Manager version.

Production deployment requires the repository's explicit production acknowledgement and should be rehearsed in a synthetic staging project first.

## Cost and free-tier considerations

The architecture is intentionally compatible with low-idle-cost personal use:

- Cloud Run uses request-based billing and can scale to zero;
- Firestore is the primary durable record store;
- Pub/Sub is used only for concrete durable async work;
- optional providers remain disabled until needed;
- provider usage is bounded by application-level request/token/call limits.

This is **free-tier-aware**, not a guarantee of zero cost. Firestore backups/TTL behavior, external providers, network egress, and model usage can incur charges.

## Security notes

- local `AUTH_MODE=development` is a development convenience, not production authentication;
- deployed API and worker services use separate service identities;
- the API validates end-user identity independently of Cloud Run service identity;
- production/staging origins are explicit allowlists;
- provider credentials belong in Secret Manager;
- research/provider outputs are bounded and validated;
- persistent memory retains attribution/provenance;
- external evidence has freshness/retention semantics separate from memory;
- account export/deletion controls remain gated operational capabilities.

Do not put personal data, provider credentials, service-account keys, or production environment files in version control.

## Documentation

Detailed documentation lives in `docs/`.

Useful entry points include:

```text
docs/project-brief.md
docs/architecture.md
docs/api-contract.md
docs/gcp-deployment.md
docs/research-agent.md
docs/dependency-management.md
docs/decisions/
```

## License

No license is currently specified. Add an explicit `LICENSE` file before treating the repository as generally reusable open-source software.
