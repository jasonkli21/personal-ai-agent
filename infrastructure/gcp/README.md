# GCP deployment

The runnable initial topology is defined in [the deployment guide](../../docs/gcp-deployment.md). `deploy.sh` creates or reuses the minimum GCP resources, then deploys three Cloud Run services:

- `personal-ai-api` — FastAPI API.
- `personal-ai-worker` — Pub/Sub push target for asynchronous work.
- `personal-ai-web` — Next.js UI, including `/api/health`, which verifies API connectivity server-side.

Use `deploy.sh PROJECT_ID [REGION] [MODEL_SECRET_NAME] [AI_MODEL]` after installing and authenticating the Google Cloud CLI. The defaults are `us-central1`, `personal-ai-gemini-api-key`, and `gemini-2.5-flash`.

The model-key secret must already exist and have a current version. The script creates or reuses a dedicated API runtime service account, grants it access to that one secret and Firestore, and supplies it as `AI_API_KEY` with Cloud Run's `--set-secrets` mechanism. It never reads or prints the key. It also supplies the project ID and model configuration required by the Phase 1 API.

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

The worker and Pub/Sub subscription are retained by the bootstrap topology, but
Phase 1 chat never publishes a Pub/Sub message. The worker is therefore idle.
