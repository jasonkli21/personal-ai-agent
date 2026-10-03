# GCP deployment

The personal-use deployment topology is defined in [the deployment guide](../../docs/gcp-deployment.md). `deploy.sh` requires an explicit staging/production target and deploys three Cloud Run services:

- `personal-ai-api` — FastAPI API.
- `personal-ai-worker` — Pub/Sub push target for asynchronous work.
- `personal-ai-web` — Next.js UI, including `/api/health`, which verifies API connectivity server-side.

Use `deploy.sh staging PROJECT_ID REGION MODEL_SECRET_NAME AI_MODEL GOOGLE_OAUTH_CLIENT_ID ALLOWED_OWNER_EMAIL HTTPS_WEB_ORIGIN NUMERIC_SECRET_VERSION` after installing and authenticating the Google Cloud CLI. Production additionally requires `PRODUCTION_DEPLOY_ACK=I_REVIEWED_THE_PRODUCTION_CHANGE` after the staging and release gates pass. The defaults for region, secret name, and model ID are `us-central1`, `personal-ai-gemini-api-key`, and `gemini-2.5-flash`, but pass all values explicitly for a release.

The model-key secret and numeric version must already exist. The script rejects a dirty checkout and a `latest` binding, builds from the committed revision, resolves container tags to immutable digests, and records the revision/tag/version in its output. It creates separate API, web, worker, Pub/Sub invoker, and maintenance invoker service accounts. Only the web service identity can invoke the private API; the worker is private and independently validates its configured Google-signed OIDC tokens. Secret values are never read or printed. The maintenance schedule is created paused and its runtime gate stays off. Export/deletion and optional feature gates stay off until their release gates are approved.

## Firestore repository indexes and local emulator

The Phase 1 conversation repositories use the composite indexes in
[`firestore.indexes.json`](../../firestore.indexes.json). `deploy.sh` creates
them when missing. To create them independently of a full deployment, run:

```sh
gcloud firestore indexes composite create \
  --collection-group=conversations \
  --field-config=field-path=owner_id,order=ascending \
  --field-config=field-path=updated_at,order=descending
gcloud firestore indexes composite create \
  --collection-group=messages \
  --field-config=field-path=owner_id,order=ascending \
  --field-config=field-path=conversation_id,order=ascending \
  --field-config=field-path=created_at,order=ascending
```

For manual local persistence checks, start the Firestore emulator and set
`FIRESTORE_PROJECT_ID` plus `FIRESTORE_EMULATOR_HOST` in `backend/.env`. The
repositories automatically use the emulator host exposed by the Google client;
automated tests use `InMemoryConversationRepository` and
`InMemoryMessageRepository` instead and make no Firestore calls.

The worker and authenticated Pub/Sub subscription support the gated Phase 4
memory lifecycle path. API and worker runtimes both receive topic-scoped
publisher access; the worker maintenance path republishes pending jobs. A separate Cloud Scheduler identity invokes bounded
maintenance; the created schedule is paused and maintenance remains disabled
until a staging rehearsal.

Optional `BACKUP_ENABLED`, `MAINTENANCE_ENABLED`, `EXPORT_ENABLED`, and
`DELETION_ENABLED` environment switches default to `false`. Backup opt-in adds
a daily 30-day Firestore schedule only if no schedule exists. Export is
available from `/account` when enabled. Deletion stops at an audited operator
review state; this release does not physically erase owner records or backups.

Phase 3 memory gates (`MEMORY_ENABLED`, `MEMORY_EXTRACTION_ENABLED`,
`MEMORY_INSPECTION_ENABLED`) are explicitly false in bootstrap deployments.
Memory KNN requires a composite vector index matching the configured dimension;
provision it and wait for READY before intentionally enabling retrieval. The
bootstrap does not provision the optional memory index. See the
[Phase 3 guide](../../docs/phase-3-implementation-guide.md#provision-vector-indexes-before-enabling-retrieval).

The Phase 4 worker is a separate private ASGI app. All memory experiment gates remain
disabled in bootstrap. See [Phase 4 deployment/recovery](../../docs/phase-4-implementation-guide.md)
for required indexes, IAM identities, optional synthetic checks and bounded republish.
