# GCP deployment

## Minimal runnable architecture

```text
Browser
  |
  v
Cloud Run: public personal-ai-web (Next.js; Google sign-in shell)
  |  server-side /api proxy; web service identity plus end-user ID token
  v
Cloud Run: private personal-ai-api (FastAPI) ----> Firestore (Native mode)
  |  chat and bounded research run in direct SSE requests
  |  gated post-terminal memory work persists lifecycle jobs
  v
Pub/Sub topic: personal-ai-async
  |
  v
Cloud Run: private personal-ai-worker -> fenced memory-lifecycle job processing

The API reads its Gemini credential from Secret Manager. The worker and
Pub/Sub lifecycle path are deployed but disabled by default. Phase 1 chat and
Phase 5 research do not publish research or token-streaming work to Pub/Sub.
```

This keeps chat and bounded research in the direct request path. Pub/Sub is used
for gated durable Phase 4 memory-lifecycle notifications with fencing and
recovery. Other asynchronous work needs its own concrete requirement.

## Components

| Concern | Technology | Initial responsibility |
| --- | --- | --- |
| UI | Next.js + React + TypeScript on Cloud Run | Chat, research and decision-result interface |
| API | FastAPI + Uvicorn on Cloud Run | HTTP API, orchestration, streaming |
| Async worker | FastAPI on Cloud Run + authenticated Pub/Sub push | Gated durable memory-lifecycle jobs |
| Durable data | Firestore Native mode | Conversations, memories, bounded research sessions, canonical research entities/claims, and decision snapshots |
| Secrets | Secret Manager | Gemini key now; other provider keys only when deliberately configured |
| Delivery | Cloud Build + Artifact Registry + Cloud Run | Build from a clean committed revision and deploy immutable image digests |

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

5. Create a Google OAuth web client. Configure its authorized JavaScript origin
   to match the exact HTTPS web origin. Choose one exact allowed Google account
   email; for a non-Gmail Workspace account, the deployment also requires the
   matching verified hosted-domain claim.
6. From a clean, reviewed commit in the repository root, run:

```bash
chmod +x infrastructure/gcp/deploy.sh
infrastructure/gcp/deploy.sh staging YOUR_STAGING_PROJECT us-central1 \
  personal-ai-gemini-api-key gemini-2.5-flash \
  YOUR_GOOGLE_OAUTH_WEB_CLIENT_ID.apps.googleusercontent.com \
  owner@gmail.com https://personal.example 2
```

Arguments are target environment (`staging` or `production`), project, region,
secret name, model ID, OAuth client ID, exact owner email, exact HTTPS web
origin, and a numeric Secret Manager version. The script rejects dirty working
trees and `latest` secret references. Production additionally requires
`PRODUCTION_DEPLOY_ACK=I_REVIEWED_THE_PRODUCTION_CHANGE`; that guard does not
replace the staging rehearsal and approval listed in the release checklist.

The script enables required APIs, creates the default Firestore database and
indexes, builds backend/frontend images from the reviewed commit, resolves each
image tag to a digest, and deploys that digest. It creates separate API, web,
worker, Pub/Sub-invoker, and maintenance-invoker service accounts. The API
requires Cloud Run IAM and admits only the web runtime identity; the web proxy
adds its service identity token and forwards the end-user token separately.
The worker requires the Pub/Sub OIDC token with an exact audience and invoker
email. Cloud Scheduler uses a different invoker identity. The model key is
injected from the explicit numeric Secret Manager version, never from an
environment file or command-line value. The web sign-in shell is public; API
data routes remain unavailable until both browser identity and service IAM pass.

The script creates the bounded maintenance schedule paused. By default it
leaves `MAINTENANCE_ENABLED`, `BACKUP_ENABLED`, `EXPORT_ENABLED`, and
`DELETION_ENABLED` false. Set those exact environment variables to `true` only
for a reviewed staging rehearsal. `BACKUP_ENABLED=true` creates a daily
30-day Firestore backup schedule only when none exists; it does not test
restore or update an existing schedule. The `/account` page displays export
and deletion controls only when the corresponding runtime flag is on, and
deletion confirmation currently queues operator review without erasing data.
No cloud deployment runs as part of repository implementation. Start
in a separate synthetic staging project, rehearse sign-in, owner isolation,
provider failure, worker retries, rollback, export, restore, and deletion before
considering production.

The example retains `gemini-2.5-flash` until an opt-in compatibility check
validates a newer stable Flash candidate such as
[`gemini-3.8-flash`](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
through this repository's generation, provider-authoritative counting,
streaming, summary/extraction, and strict
research-output paths. `AI_MODEL` is runtime configuration; the application
context/output ceilings still require explicit validation. Embedding-model
changes are a separate stored-vector and Firestore-index migration; see the
[Phase 3 guide](phase-3-implementation-guide.md).

### Verify the end-to-end baseline

Use the [Phase 1 deployment checklist](phase-1-deployment-checklist.md) after deployment. It verifies the web-to-API path, a streamed chat turn, and Firestore persistence. A successful `/api/health` response confirms that the web service can reach the API server-side; it does not exercise the model or Firestore.

## Free-tier-aware defaults

- Cloud Run services use request-based billing with `min-instances=0`, allowing them to scale to zero while idle. Cloud Run's free allowance is usage-based, and charges can apply after it is exhausted or for items such as network egress. [Cloud Run pricing](https://cloud.google.com/run/pricing)
- Firestore's single free database includes 1 GiB storage, 50,000 reads/day, 20,000 writes/day, 20,000 deletes/day, and 10 GiB/month outbound transfer. Features such as TTL deletes and backups are not within that free usage. [Firestore pricing](https://firebase.google.com/docs/firestore/pricing)
- Pub/Sub includes the first 10 GiB of throughput per billing account each month; use short messages and a single subscription initially. [Pub/Sub pricing](https://cloud.google.com/pubsub/pricing)
- Secret Manager includes six active secret versions and 10,000 access operations each month. Add secrets only when an adapter needs them. [Secret Manager pricing](https://cloud.google.com/secret-manager/pricing)

Keep a billing budget and usage alerts enabled. External model, web-search, travel, places, and shopping providers have independent pricing and quotas.

Measure Firestore stored/index bytes, vector counts, and daily operations before
considering another canonical record store. Memory retrieval currently uses
Firestore vector KNN and would need a separate vector-index migration; another
document store alone cannot replace it. No current request path stores blobs or
full publisher pages, so Cloud Storage remains deferred until a concrete upload
or retained-artifact feature needs it.

## Security boundary

The public web service exposes a sign-in shell. The API is private to the web
runtime service account and separately validates the end-user Google ID token;
development `local` identity is allowed only in local/test configurations.
Cloud Run IAM and application identity are separate checks. Production remains
blocked until provider-data review, owner migration, staged IAM and worker
rehearsal, alerting, backup/restore, export fidelity, deletion propagation, and
operator approval are recorded in the [Phase 9 checklist](phase-9-release-checklist.md).


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
push subscriptions and grants distinct runtime and invoker permissions. Both API and worker runtimes
can publish to the lifecycle topic, because worker maintenance republishes
pending notifications. Before enabling a synthetic experiment, provision all Phase 4 indexes
from `firestore.indexes.json`, including derived/typed vector indexes with matching
dimensions, maintenance, event-sequence, reverse-dependency and pending/retry queries.
Wait for readiness; the bootstrap provisions baseline chat/summary and Phase 9 research-expiry indexes. See the
[Phase 4 guide](phase-4-implementation-guide.md) for explicit notification recovery,
attempt/lease bounds, opt-in checks and current verification limitations. The private
worker independently verifies its Pub/Sub identity token; deployed API requests never
use the `local` owner.

## Phase 5 opt-in research deployment

The bootstrap explicitly sets research/inspection/storage-rights gates to false.
It does not enable a search key or provision optional research field-index
exemptions. Before a deliberate synthetic deployment check, follow the
[Phase 5 guide](phase-5-implementation-guide.md) for licensed snippet storage,
Secret Manager wiring, index exemptions, provider-wide quotas and retention.
Research runs in the API request; the worker receives no research jobs.
Existing Phase 1–8 records remain under `local` until the
[reviewed owner migration](phase-9-owner-migration.md) is dry-run and explicitly
applied; deployment does not migrate data.

## Phase 6 opt-in decision deployment

Decision creation and result retrieval are gated by `DECISION_ENABLED`; the
development inspector also requires `DECISION_INSPECTION_ENABLED`. Both remain
false by default, and this deployment script does not enable them. Before an
opt-in synthetic emulator or cloud check, provision the Phase 6 composite
indexes from `firestore.indexes.json` for canonical entities, aliases, claims,
matches, decision evaluations, and evidence-to-claim lookup, then wait for
readiness. Firestore transaction behavior and index readiness have not yet
been verified against an emulator or deployed project. Decision snapshots
retain source attribution metadata subject to the source provider's storage,
retention, and deletion terms. Local/test development continues to use the fixed
`local` owner; deployed requests do not fall back to it.
