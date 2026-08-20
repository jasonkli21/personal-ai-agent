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

Cloud Run services read provider credentials from Secret Manager when real LLM
and search adapters are introduced.
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

1. Install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) and authenticate with an account permitted to create the listed resources.
2. Create a GCP project with billing enabled. Free quotas are applied before usage charges, but deployment is not a promise of zero cost.
3. From the repository root, run:

```bash
chmod +x infrastructure/gcp/deploy.sh
infrastructure/gcp/deploy.sh YOUR_PROJECT_ID us-central1
```

The script enables required APIs, creates the default Firestore database if absent, creates a Pub/Sub topic and authenticated push subscription, then deploys the API, worker, and web service. It prints the web URL and health-check URL.

### Verify the end-to-end baseline

Open the printed `/api/health` URL. The web service calls the API server-side, so a successful response confirms that both Cloud Run services are deployed and connected. Firestore and Pub/Sub are provisioned for the next implementation phases; no user data or jobs are written by the initial health check.

## Free-tier-aware defaults

- Cloud Run services use request-based billing with `min-instances=0`, allowing them to scale to zero while idle. Cloud Run's free allowance is usage-based, and charges can apply after it is exhausted or for items such as network egress. [Cloud Run pricing](https://cloud.google.com/run/pricing)
- Firestore's single free database includes 1 GiB storage, 50,000 reads/day, 20,000 writes/day, 20,000 deletes/day, and 10 GiB/month outbound transfer. Features such as TTL deletes and backups are not within that free usage. [Firestore pricing](https://firebase.google.com/docs/firestore/pricing)
- Pub/Sub includes the first 10 GiB of throughput per billing account each month; use short messages and a single subscription initially. [Pub/Sub pricing](https://cloud.google.com/pubsub/pricing)
- Secret Manager includes six active secret versions and 10,000 access operations each month. Add secrets only when an adapter needs them. [Secret Manager pricing](https://cloud.google.com/secret-manager/pricing)

Keep a billing budget and usage alerts enabled. External model, web-search, travel, places, and shopping providers have independent pricing and quotas.

## Security boundary

The bootstrap makes the web and API endpoints public so the two-service health check runs without identity infrastructure. It is not ready for personal data. Before storing real chats or provider keys, implement Phase 9 authentication and authorization, restrict API ingress as appropriate, and add secrets through Secret Manager rather than environment files.
