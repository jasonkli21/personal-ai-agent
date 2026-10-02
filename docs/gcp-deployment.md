# GCP deployment

## Minimal runnable architecture

```text
Browser
  |
  v
Cloud Run: personal-ai-web (Next.js)
  |  server-side /api/health and future API proxy
  v
Cloud Run: personal-ai-api (FastAPI) ----> Firestore (Native mode)
  |
  +----> Pub/Sub topic: personal-ai-async
                         |
                         v
                Cloud Run: personal-ai-worker (FastAPI push target)
                         |
                  future consolidation / research / expiry jobs

The Phase 1 API reads its Gemini credential from Secret Manager. The worker
remains deployed but idle; Phase 1 chat does not publish Pub/Sub messages.
```

This keeps the synchronous chat and research request path simple. Pub/Sub is not part of initial chat latency; it is reserved for durable work that can happen later, such as memory consolidation, evidence-expiry maintenance, or longer research tasks.

## Components

| Concern | Technology | Initial responsibility |
| --- | --- | --- |
| UI | Next.js + React + TypeScript on Cloud Run | Chat and research interface |
| API | FastAPI + Uvicorn on Cloud Run | HTTP API, orchestration, streaming |
| Async worker | FastAPI on Cloud Run + Pub/Sub push | Acknowledge and later execute non-interactive jobs |
| Durable data | Firestore Native mode | Conversations, memories, research sessions, evidence, entities |
| Secrets | Secret Manager | LLM, search, places, and travel-provider credentials |
| Delivery | Docker + Cloud Run source deployment | Build and deploy each service |

## Deploy

### Prerequisites

1. Install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) and authenticate with an account permitted to administer Cloud Run, Firestore, Pub/Sub, Secret Manager, service accounts, and IAM bindings in the target project.
2. Create a GCP project with billing enabled. Free quotas are applied before usage charges, but deployment is not a promise of zero cost.
3. Create a billing budget and at least one alert before deploying. Review it after the first smoke test.
4. Create the Gemini API-key secret without putting its value in a committed file or shell history. The default name expected by the script is `personal-ai-gemini-api-key`:

```bash
printf '%s' "$GEMINI_API_KEY" | gcloud secrets create personal-ai-gemini-api-key \
  --replication-policy=automatic --data-file=-
```

Set `GEMINI_API_KEY` only in the current terminal or use your secret-entry workflow; do not paste the key into a command-line argument. If the secret already exists, add a new version with `gcloud secrets versions add personal-ai-gemini-api-key --data-file=-` and pipe the value in the same way.

5. From the repository root, run:

```bash
chmod +x infrastructure/gcp/deploy.sh
infrastructure/gcp/deploy.sh YOUR_PROJECT_ID us-central1 personal-ai-gemini-api-key gemini-2.5-flash
```

The script enables required APIs, creates the default Firestore database and
required composite indexes if absent, creates a Pub/Sub topic and authenticated
push subscription, creates or reuses a dedicated API runtime service account,
grants it the named-secret and Firestore permissions, then deploys the API,
worker, and web service. It injects `AI_API_KEY` using Secret Manager rather
than an environment file or command-line value. It prints the web URL and
health-check URL, never the secret.

### Verify the end-to-end baseline

Use the [Phase 1 deployment checklist](phase-1-deployment-checklist.md) after deployment. It verifies the web-to-API path, a streamed chat turn, and Firestore persistence. A successful `/api/health` response confirms that the web service can reach the API server-side; it does not exercise the model or Firestore.

## Free-tier-aware defaults

- Cloud Run services use request-based billing with `min-instances=0`, allowing them to scale to zero while idle. Cloud Run's free allowance is usage-based, and charges can apply after it is exhausted or for items such as network egress. [Cloud Run pricing](https://cloud.google.com/run/pricing)
- Firestore's single free database includes 1 GiB storage, 50,000 reads/day, 20,000 writes/day, 20,000 deletes/day, and 10 GiB/month outbound transfer. Features such as TTL deletes and backups are not within that free usage. [Firestore pricing](https://firebase.google.com/docs/firestore/pricing)
- Pub/Sub includes the first 10 GiB of throughput per billing account each month; use short messages and a single subscription initially. [Pub/Sub pricing](https://cloud.google.com/pubsub/pricing)
- Secret Manager includes six active secret versions and 10,000 access operations each month. Add secrets only when an adapter needs them. [Secret Manager pricing](https://cloud.google.com/secret-manager/pricing)

Keep a billing budget and usage alerts enabled. External model, web-search, travel, places, and shopping providers have independent pricing and quotas.

## Security boundary

The bootstrap makes the web and API endpoints public so the two-service health check runs without identity infrastructure. It is unsuitable for sensitive personal data. Before storing real chats or provider keys, implement Phase 9 authentication and authorization, restrict API ingress as appropriate, and add secrets through Secret Manager rather than environment files.


## Phase 2 deployment checks

The deploy script provisions the `conversation_summaries` owner/conversation
index and explicitly sets `CONTEXT_INSPECTION_ENABLED=false` for API and web.
Confirm `/development/context`, `/api/conversations/UUID/context`, and the API's
`/v1/conversations/UUID/context` return 404 with the flag disabled. Summary refresh
runs synchronously in the API and introduces no Pub/Sub work.

Validate the configured model against the application context/output ceilings;
see [Phase 2 configuration and verification](phase-2-implementation-guide.md).
Use synthetic long conversations for the opt-in provider quality check and verify
summary-backed streaming plus refresh/restart persistence in the emulator/deployed
store. These external checks have not been run in the recorded local session.

## Phase 4 private worker and gated indexes

The worker uses `personal_ai.worker:app`, with `/tasks/memory` separate from the
public API. Bootstrap sets all lifecycle gates false, updates existing authenticated
push subscriptions and grants distinct worker runtime, API publisher and push invoker
permissions. Before enabling a synthetic experiment, provision all Phase 4 indexes
from `firestore.indexes.json`, including derived/typed vector indexes with matching
dimensions, maintenance, event-sequence, reverse-dependency and pending/retry queries.
Wait for readiness; the bootstrap provisions only Phase 1–2 indexes. See the
[Phase 4 guide](phase-4-implementation-guide.md) for explicit notification recovery,
attempt/lease bounds, opt-in checks and current verification limitations. A private
worker does not authenticate the public chat's fixed `local` owner.

## Phase 5 opt-in research deployment

The bootstrap explicitly sets research/inspection/storage-rights gates to false.
It does not enable a search key or provision optional research field-index
exemptions. Before a deliberate synthetic deployment check, follow the
[Phase 5 guide](phase-5-implementation-guide.md) for licensed snippet storage,
Secret Manager wiring, index exemptions, provider-wide quotas and retention.
Research runs in the API request; the worker receives no research jobs.
The public fixed-owner bootstrap remains unsuitable for personal data.
