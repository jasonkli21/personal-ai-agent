# GCP deployment

The runnable initial topology is defined in [the deployment guide](../../docs/gcp-deployment.md). `deploy.sh` creates or reuses the minimum GCP resources, then deploys three Cloud Run services:

- `personal-ai-api` — FastAPI API.
- `personal-ai-worker` — Pub/Sub push target for asynchronous work.
- `personal-ai-web` — Next.js UI, including `/api/health`, which verifies API connectivity server-side.

Use `deploy.sh PROJECT_ID REGION` after installing and authenticating the Google Cloud CLI. Default region: `us-central1`.

## Firestore repository indexes and local emulator

The Phase 1 conversation repositories use the composite indexes in
[`firestore.indexes.json`](../../firestore.indexes.json). Create them once per
project with:

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
